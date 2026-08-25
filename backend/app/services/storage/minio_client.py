"""MinIO 对象存储封装（M13 D5）。

只承担两类非关键路径产物：①理解报告导出件 ②索引完成后的解析产物快照。
仓库工作副本一律留在本地盘——git pull 与 tree-sitter 必须真实文件系统。

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
            )
        return _client


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
