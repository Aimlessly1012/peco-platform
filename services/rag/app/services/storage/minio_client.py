"""MinIO 对象存储封装（M13 D5）。

承担三类对象：①理解报告导出件 ②索引完成后的解析产物快照（以上非关键路径）
③**源码 git bundle**——M16 起它是每个项目源码的唯一持久层，本地盘只剩任务级
临时工作区。bundle 上传失败仍只记 warning：下次任务的容错链会退回 clone 远端。

MINIO_ACCESS_KEY 为空 = 整个模块 no-op（返回 None），调用方不必写分支判断；
这也是本地开发和不想跑 MinIO 的部署形态的默认状态。

SDK 是同步的（urllib3），异步调用方一律用 asyncio.to_thread 包一层。
"""
import io
import logging
import threading

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None
_lock = threading.Lock()
_bucket_ready = False


def storage_enabled() -> bool:
    """access key 是总开关：为空即全部降级为 no-op。"""
    return bool(settings.minio_access_key)


def get_client():
    """惰性建客户端。未启用返回 None。"""
    global _client
    if not storage_enabled():
        return None
    with _lock:
        if _client is None:
            from minio import Minio

            _client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
                http_client=_http_client(),
            )
        return _client


def _http_client():
    """带显式超时的连接池（M17 D8）。

    SDK 默认的 http_client 不设超时且 retries=5 带退避——MinIO「端口能连上但不
    响应」时，一次下载能挂住分钟级，把索引任务卡死在取码这一步。这里把连接/读
    超时与重试次数都钉死，让它在秒级内失败，走既有降级路径（下载失败→回退
    clone，上传失败→warning）。只改失败路径，成功路径行为不变。
    """
    import urllib3

    return urllib3.PoolManager(
        timeout=urllib3.Timeout(
            connect=settings.minio_connect_timeout_seconds,
            read=settings.minio_read_timeout_seconds,
        ),
        retries=urllib3.Retry(total=1, backoff_factor=0.2, redirect=False),
    )


def reset_client() -> None:
    """丢掉缓存的客户端与建桶状态（测试用；配置变了也得走这个）。"""
    global _client, _bucket_ready
    with _lock:
        _client = None
        _bucket_ready = False


def ensure_bucket() -> bool:
    """确保桶存在（幂等）。未启用返回 False；失败抛异常，由调用方决定怎么降级。"""
    global _bucket_ready
    client = get_client()
    if client is None:
        return False
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
        logger.info("已创建 MinIO 桶 %s", settings.minio_bucket)
    _bucket_ready = True
    return True


def ensure_bucket_quietly() -> bool:
    """启动钩子用：MinIO 不可用不能拦住 API 启动（artifact-storage 是非关键路径）。"""
    try:
        if ensure_bucket():
            logger.info(
                "MinIO 就绪：%s/%s", settings.minio_endpoint, settings.minio_bucket
            )
            return True
    except Exception as e:  # noqa: BLE001 — 启动期不可用只是降级，不是故障
        logger.warning("MinIO 建桶失败，产物存储本次不可用：%s", e)
    return False


def put_bytes(
    key: str, payload: bytes, content_type: str = "application/octet-stream"
) -> str | None:
    """上传对象并返回 key；未启用返回 None。

    失败一律抛异常——调用方（导出端点、索引归档）各自降级为 warning，这里不吞。
    """
    client = get_client()
    if client is None:
        return None
    if not _bucket_ready:
        # 启动时建桶失败过也能自愈，不必重启进程
        ensure_bucket()
    client.put_object(
        settings.minio_bucket,
        key,
        io.BytesIO(payload),
        length=len(payload),
        content_type=content_type,
    )
    return key


def upload_file(
    key: str, file_path: str, content_type: str = "application/octet-stream"
) -> str | None:
    """上传本地文件（流式，适合 tarball 这类不该整读进内存的对象）。语义同 put_bytes。"""
    client = get_client()
    if client is None:
        return None
    if not _bucket_ready:
        ensure_bucket()
    client.fput_object(settings.minio_bucket, key, file_path, content_type=content_type)
    return key


def download_file(key: str, dest_path: str) -> bool:
    """把对象下载到本地文件。存在并下载成功返回 True。

    未启用、对象不存在、MinIO 不可达一律返回 False 而不抛——调用方（bundle 恢复）
    对这三种情况的处理完全一样：退回直接 clone 远端。
    """
    client = get_client()
    if client is None:
        return False
    try:
        client.fget_object(settings.minio_bucket, key, dest_path)
        return True
    except Exception as e:  # noqa: BLE001 — 见 docstring
        logger.info("对象不可用（%s）：%s", key, e)
        return False


def list_keys(prefix: str) -> list[tuple[str, object]]:
    """列出前缀下的对象 (key, last_modified)。未启用返回空列表。"""
    client = get_client()
    if client is None:
        return []
    return [
        (obj.object_name, obj.last_modified)
        for obj in client.list_objects(settings.minio_bucket, prefix=prefix)
    ]


def remove_key(key: str) -> None:
    """删除对象（幂等：不存在也不报错——S3 DeleteObject 语义本就如此）。"""
    client = get_client()
    if client is None:
        return
    client.remove_object(settings.minio_bucket, key)
