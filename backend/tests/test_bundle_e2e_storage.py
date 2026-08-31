"""存储层硬化与故障演练（M17 组 4）。

M16 已覆盖的容错矩阵（bundle 缺失/损坏/下载抛错/存储禁用/fetch 失败）在
test_bundle_storage.py，这里不重复。本文件补的是 M17 新增的三块：

- 4.1 产包自校验：坏包不覆盖好包
- 4.2 客户端超时：MinIO 挂起时在秒级内降级，而不是把索引任务拖住
- 4.3/4.4 生命周期与矩阵缺口：多轮索引的 bundle 刷新、首传时桶不存在、
  建桶失败后自愈
- 4.5 真 MinIO 往返（integration 档，吃 CI 的 MinIO 容器）
"""
import socket
import threading
import time
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.ingest import git_ops
from app.services.ingest.git_ops import (
    BundleVerifyError,
    bundle_key,
    clone_fresh,
    diff_changed_files,
    export_bundle,
    restore_workdir,
)
from app.services.storage import minio_client
from tests.helpers.repos import write_and_commit

# ---------------- 4.1 产包自校验（硬化一） ----------------


def test_verify_rejects_a_corrupt_bundle(tmp_path, origin):
    """自校验能认出坏包——整条硬化建立在这个前提上。"""
    work = tmp_path / "w"
    clone_fresh(origin.url, work)
    broken = tmp_path / "broken.bundle"
    broken.write_bytes(b"# v2 git bundle\nnot really\n")

    with pytest.raises(BundleVerifyError):
        git_ops._verify_bundle(work, str(broken))


def test_verify_accepts_a_good_bundle(tmp_path, origin):
    """成功路径行为不变：好包照样过（这是 proposal 的行为红线）。"""
    work = tmp_path / "w"
    clone_fresh(origin.url, work)
    good = tmp_path / "good.bundle"
    git_ops._create_bundle(work, str(good))

    git_ops._verify_bundle(work, str(good))     # 不抛即通过


def test_corrupt_bundle_is_not_uploaded(tmp_path, origin, store, monkeypatch):
    """spec 场景: 坏包不覆盖好包。

    先正常传一份好包，再让产包过程"受损"，断言 MinIO 里那份**一个字节都没变**。
    固定 key 是覆盖写，这正是硬化要防的事故。
    """
    work = tmp_path / "w"
    clone_fresh(origin.url, work)
    export_bundle("p1", work)
    good_bytes = store["path_of"](bundle_key("p1")).read_bytes()
    uploads_before = len(store["uploaded"])

    def write_garbage(_repo_dir, out_path):
        Path(out_path).write_bytes(b"truncated write")

    monkeypatch.setattr(git_ops, "_create_bundle", write_garbage)

    with pytest.raises(BundleVerifyError):
        export_bundle("p1", work)

    assert store["path_of"](bundle_key("p1")).read_bytes() == good_bytes
    assert len(store["uploaded"]) == uploads_before      # 压根没发起上传


async def test_verify_failure_becomes_a_distinguishable_warning(
    tmp_path, origin, store, monkeypatch
):
    """spec 场景: 任务 stats 含校验失败 warning，任务成败不受影响。"""
    from app.services.ingest import pipeline

    monkeypatch.setattr(pipeline, "storage_enabled", lambda: True)
    work = tmp_path / "w"
    clone_fresh(origin.url, work)
    monkeypatch.setattr(
        git_ops, "_create_bundle",
        lambda _d, out: Path(out).write_bytes(b"garbage"),
    )
    stats = {"chunks": 7}

    await pipeline.archive_repo_bundle("p1", work, stats)   # 不抛

    assert "repo_bundle_key" not in stats
    assert "自校验失败" in stats["repo_bundle_warning"]
    assert "保留远端旧包" in stats["repo_bundle_warning"]
    assert stats["chunks"] == 7


# ---------------- 4.2 客户端超时（硬化二） ----------------


@pytest.fixture
def hung_server():
    """一个接受连接后就装死的 TCP 服务——模拟"端口通但不响应"的 MinIO。"""
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    held = []
    stop = threading.Event()

    def accept_and_hang():
        server.settimeout(0.5)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                continue
            held.append(conn)      # 收下就不管了，一个字节都不回

    thread = threading.Thread(target=accept_and_hang, daemon=True)
    thread.start()
    yield f"127.0.0.1:{server.getsockname()[1]}"
    stop.set()
    thread.join(2)
    for conn in held:
        conn.close()
    server.close()


@pytest.fixture
def hung_minio(hung_server, monkeypatch):
    monkeypatch.setattr(settings, "minio_endpoint", hung_server)
    monkeypatch.setattr(settings, "minio_access_key", "k")
    monkeypatch.setattr(settings, "minio_secret_key", "s")
    monkeypatch.setattr(settings, "minio_secure", False)
    monkeypatch.setattr(settings, "minio_read_timeout_seconds", 1)
    monkeypatch.setattr(settings, "minio_connect_timeout_seconds", 1)
    minio_client.reset_client()
    yield hung_server
    minio_client.reset_client()


def test_http_client_carries_explicit_timeouts(monkeypatch):
    monkeypatch.setattr(settings, "minio_connect_timeout_seconds", 3)
    monkeypatch.setattr(settings, "minio_read_timeout_seconds", 7)

    pool = minio_client._http_client()

    assert pool.connection_pool_kw["timeout"].connect_timeout == 3
    assert pool.connection_pool_kw["timeout"].read_timeout == 7


def test_download_gives_up_within_the_timeout(tmp_path, hung_minio):
    """spec 场景: MinIO 挂起不阻塞索引——下载在超时上限内放弃并返回 False。"""
    started = time.monotonic()

    ok = minio_client.download_file("repo-bundles/p1.bundle", str(tmp_path / "out"))

    elapsed = time.monotonic() - started
    assert ok is False                 # 语义不变：不抛，返回 False 让调用方回退 clone
    assert elapsed < 15, f"挂起了 {elapsed:.1f}s，超时没生效"


def test_restore_falls_back_to_clone_when_minio_hangs(tmp_path, origin, hung_minio):
    """挂起场景下取码链路整体仍然走得通——回退直接 clone 远端。"""
    work = tmp_path / "w"
    work.mkdir()
    started = time.monotonic()

    sha, source = restore_workdir("p1", origin.url, work)

    assert (sha, source) == (origin.head, "clone")
    assert time.monotonic() - started < 20


# ---------------- 4.3 bundle 生命周期（多轮索引） ----------------


def test_bundle_lifecycle_across_two_index_rounds(tmp_path, origin, store):
    """spec 场景: 二次索引从 bundle 恢复。

    模拟连续两轮索引的取码-归档闭环：
      第一轮 本地空 → clone 远端 → 产 bundle
      第二轮 本地空 + 远端有新提交 → 从 bundle 恢复 + fetch 增量 → 刷新 bundle
    """
    round1 = tmp_path / "r1"
    round1.mkdir()
    sha1, source1 = restore_workdir("p1", origin.url, round1)
    export_bundle("p1", round1)

    assert source1 == "clone"            # 第一轮没有 bundle 可用
    bundle_after_first = store["path_of"](bundle_key("p1")).read_bytes()

    third = write_and_commit(
        origin.repo, origin.path, {"c.py": "def c():\n    return 3\n"}, "third"
    )

    round2 = tmp_path / "r2"
    round2.mkdir()
    sha2, source2 = restore_workdir("p1", origin.url, round2)

    assert source2 == "bundle"           # 第二轮走 bundle 恢复
    assert sha2 == third
    # 增量正确：上一轮的 commit 仍在历史里，diff 拿得到
    changed = diff_changed_files(round2, sha1, sha2)
    assert changed.added == ["c.py"]

    export_bundle("p1", round2)
    assert store["path_of"](bundle_key("p1")).read_bytes() != bundle_after_first, (
        "第二轮结束后 bundle 必须刷新到最新 commit"
    )


def test_third_round_restores_the_refreshed_bundle(tmp_path, origin, store):
    """刷新后的 bundle 确实可用——不然"刷新了"只是文件变了而已。"""
    for name in ("r1", "r2"):
        work = tmp_path / name
        work.mkdir()
        restore_workdir("p1", origin.url, work)
        export_bundle("p1", work)

    write_and_commit(origin.repo, origin.path, {"d.py": "d = 4\n"}, "fourth")
    final = tmp_path / "r3"
    final.mkdir()

    sha, source = restore_workdir("p1", origin.url, final)

    assert source == "bundle"
    assert (final / "d.py").exists()
    assert sha == origin.repo.head.commit.hexsha


# ---------------- 4.4 故障矩阵缺口 ----------------


class FakeMinioSDK:
    """够用的假 SDK：能造「桶不存在」「建桶第一次失败」两种情形。"""

    def __init__(self, *, bucket_exists=False, fail_makes=0):
        self.buckets = {settings.minio_bucket} if bucket_exists else set()
        self.objects: dict[str, bytes] = {}
        self.make_calls = 0
        self._fail_makes = fail_makes

    def bucket_exists(self, name):
        return name in self.buckets

    def make_bucket(self, name):
        self.make_calls += 1
        if self.make_calls <= self._fail_makes:
            raise OSError("建桶失败（MinIO 刚起来还没就绪）")
        self.buckets.add(name)

    def fput_object(self, bucket, key, path, content_type=None):
        if bucket not in self.buckets:
            raise OSError("NoSuchBucket")
        self.objects[key] = Path(path).read_bytes()

    def fget_object(self, bucket, key, path):
        if key not in self.objects:
            raise OSError("NoSuchKey")
        Path(path).write_bytes(self.objects[key])


@pytest.fixture
def fake_sdk(monkeypatch):
    def install(**kwargs):
        sdk = FakeMinioSDK(**kwargs)
        monkeypatch.setattr(settings, "minio_access_key", "k")
        monkeypatch.setattr(settings, "minio_secret_key", "s")
        monkeypatch.setattr(minio_client, "_client", sdk)
        monkeypatch.setattr(minio_client, "_bucket_ready", False)
        return sdk

    yield install
    minio_client.reset_client()


def test_worker_first_upload_creates_the_bucket(tmp_path, fake_sdk):
    """worker 是第一个碰存储的进程时，桶还不存在——upload 要自己把桶建出来。

    API 进程在 lifespan 里建桶，但 worker 是独立容器：全新部署里很可能是 worker
    先跑到归档这一步。
    """
    sdk = fake_sdk(bucket_exists=False)
    payload = tmp_path / "x.bundle"
    payload.write_bytes(b"bundle-bytes")

    key = minio_client.upload_file("repo-bundles/p1.bundle", str(payload))

    assert key == "repo-bundles/p1.bundle"
    assert sdk.make_calls == 1
    assert sdk.objects["repo-bundles/p1.bundle"] == b"bundle-bytes"


def test_bucket_ready_self_heals_after_a_failure(tmp_path, fake_sdk):
    """启动时建桶失败过（MinIO 还没起来）→ 下一次上传自己重试，不必重启进程。"""
    sdk = fake_sdk(bucket_exists=False, fail_makes=1)
    payload = tmp_path / "x.bundle"
    payload.write_bytes(b"bundle-bytes")

    assert minio_client.ensure_bucket_quietly() is False    # 第一次失败，只 warning

    key = minio_client.upload_file("repo-bundles/p1.bundle", str(payload))

    assert key == "repo-bundles/p1.bundle"
    assert sdk.make_calls == 2                              # 第二次补上了
    assert minio_client._bucket_ready is True


def test_download_of_a_missing_object_returns_false(tmp_path, fake_sdk):
    """对象不存在是**正常状态**（首次索引），不该抛。"""
    fake_sdk(bucket_exists=True)

    assert minio_client.download_file("repo-bundles/nope.bundle", str(tmp_path / "o")) is False


# ---------------- 4.5 真 MinIO 往返（integration） ----------------


@pytest.fixture
def real_minio(require_minio, monkeypatch):
    endpoint, access, secret = require_minio
    bucket = "m17-e2e-test"
    monkeypatch.setattr(settings, "minio_endpoint", endpoint)
    monkeypatch.setattr(settings, "minio_access_key", access)
    monkeypatch.setattr(settings, "minio_secret_key", secret)
    monkeypatch.setattr(settings, "minio_secure", False)
    monkeypatch.setattr(settings, "minio_bucket", bucket)
    minio_client.reset_client()
    yield bucket
    minio_client.reset_client()


@pytest.mark.integration
def test_real_minio_lazy_bucket_and_roundtrip(tmp_path, origin, real_minio):
    """spec 场景: 桶惰性初始化 + bundle 上传下载往返（真 SDK，不是假存储）。"""
    work = tmp_path / "w"
    clone_fresh(origin.url, work)
    src = tmp_path / "src.bundle"
    git_ops._create_bundle(work, str(src))

    assert minio_client.ensure_bucket() is True         # 不存在就建出来
    assert minio_client.ensure_bucket() is True         # 幂等
    key = minio_client.upload_file("repo-bundles/e2e.bundle", str(src))
    assert key == "repo-bundles/e2e.bundle"

    back = tmp_path / "back.bundle"
    assert minio_client.download_file(key, str(back)) is True
    assert back.read_bytes() == src.read_bytes()

    # 下回来的包过得了自校验——这才叫往返成功，不只是字节相等
    git_ops._verify_bundle(work, str(back))
    minio_client.remove_key(key)


@pytest.mark.integration
def test_real_minio_missing_object_is_false(tmp_path, real_minio):
    minio_client.ensure_bucket()

    assert minio_client.download_file("repo-bundles/absent.bundle", str(tmp_path / "x")) is False
