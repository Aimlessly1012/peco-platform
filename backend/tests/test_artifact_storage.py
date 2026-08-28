"""对象存储单测（M13 4.1-4.3 / 5.3）。

存储层是**非关键路径**：MinIO 没配、连不上、上传失败，索引与导出都必须照常。
本文件大半篇幅在钉这一点。
"""
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.tables import Project, ProjectStatus, UnderstandingReport
from app.services.ingest.pipeline import archive_index_snapshot, build_index_snapshot
from app.services.storage import minio_client
from app.services.storage.minio_client import (
    ensure_bucket,
    ensure_bucket_quietly,
    put_bytes,
    storage_enabled,
)


class FakeMinio:
    def __init__(self, *, bucket_exists=False, fail_on_put=False, fail_on_check=False):
        self.buckets = {settings.minio_bucket} if bucket_exists else set()
        self.made: list[str] = []
        self.objects: dict[str, dict] = {}
        self._fail_on_put = fail_on_put
        self._fail_on_check = fail_on_check

    def bucket_exists(self, name):
        if self._fail_on_check:
            raise OSError("minio 不可达")
        return name in self.buckets

    def make_bucket(self, name):
        self.buckets.add(name)
        self.made.append(name)

    def put_object(self, bucket, key, data, length=None, content_type=None):
        if self._fail_on_put:
            raise OSError("minio 不可达")
        self.objects[key] = {
            "bucket": bucket, "body": data.read(),
            "length": length, "content_type": content_type,
        }


@pytest.fixture
def minio(monkeypatch):
    """装一个假 MinIO 客户端并打开存储开关；用例里按需传 fail_on_* 造故障。"""

    def install(**kwargs):
        fake = FakeMinio(**kwargs)
        monkeypatch.setattr(settings, "minio_access_key", "test-key")
        monkeypatch.setattr(settings, "minio_secret_key", "test-secret")
        monkeypatch.setattr(minio_client, "_client", fake)
        monkeypatch.setattr(minio_client, "_bucket_ready", False)
        return fake

    yield install
    minio_client.reset_client()


@pytest.fixture
def minio_off(monkeypatch):
    monkeypatch.setattr(settings, "minio_access_key", "")


# ---------------- 4.1 客户端与建桶 ----------------


def test_disabled_when_access_key_empty(minio_off):
    """spec: 凭据只来自环境变量；没配就整层 no-op，不装 MinIO 也能跑。"""
    assert storage_enabled() is False
    assert minio_client.get_client() is None
    assert ensure_bucket() is False
    assert put_bytes("k", b"x") is None


def test_first_start_creates_bucket(minio):
    """spec 场景: 全新 MinIO 实例上启动 → 桶被自动创建。"""
    fake = minio()

    assert ensure_bucket() is True
    assert fake.made == [settings.minio_bucket]


def test_existing_bucket_is_not_recreated(minio):
    fake = minio(bucket_exists=True)

    assert ensure_bucket() is True
    assert fake.made == []


def test_startup_hook_swallows_minio_failure(minio):
    """MinIO 不可用不能拦住 API 启动——它是非关键路径。"""
    minio(fail_on_check=True)

    assert ensure_bucket_quietly() is False   # 不抛异常


def test_put_bytes_uploads_with_metadata(minio):
    fake = minio(bucket_exists=True)

    key = put_bytes("reports/x.md", "内容".encode(), "text/markdown")

    assert key == "reports/x.md"
    obj = fake.objects["reports/x.md"]
    assert obj["bucket"] == settings.minio_bucket
    assert obj["body"].decode() == "内容"
    assert obj["length"] == len("内容".encode())
    assert obj["content_type"] == "text/markdown"


def test_put_bytes_creates_bucket_lazily(minio):
    """启动时建桶失败过也要能自愈，不必重启进程。"""
    fake = minio()

    put_bytes("k", b"x")

    assert fake.made == [settings.minio_bucket]


# ---------------- 4.3 索引产物快照 ----------------


def fake_file(path, language="python", modules=("api",)):
    return SimpleNamespace(path=path, language=language, modules=list(modules))


def fake_module(key="api:orders"):
    return SimpleNamespace(
        key=key, name="orders", kind="api", route_prefix="/api/orders"
    )


def snapshot_args(stats=None):
    return {
        "job_id": uuid.uuid4(), "project_id": uuid.uuid4(), "name": "mini-shop",
        "commit_sha": "abc123", "stats": stats if stats is not None else {"chunks": 2},
        "files": [fake_file("a.py"), fake_file("b.tsx", "typescript", ["web"])],
        "chunks": [
            SimpleNamespace(file_path="a.py"), SimpleNamespace(file_path="a.py"),
            SimpleNamespace(file_path="b.tsx"),
        ],
        "modules": [fake_module()],
    }


def test_snapshot_carries_modules_and_per_file_chunk_counts():
    snap = build_index_snapshot(**snapshot_args())

    assert snap["project_name"] == "mini-shop"
    assert snap["commit_sha"] == "abc123"
    assert snap["modules"] == [
        {"key": "api:orders", "name": "orders", "kind": "api",
         "route_prefix": "/api/orders"}
    ]
    by_path = {f["path"]: f for f in snap["files"]}
    assert by_path["a.py"]["chunks"] == 2
    assert by_path["b.tsx"]["chunks"] == 1
    assert by_path["b.tsx"]["modules"] == ["web"]


async def test_archive_uploads_and_records_key(minio):
    fake = minio(bucket_exists=True)
    args = snapshot_args()
    stats = args["stats"]

    await archive_index_snapshot(
        args["job_id"], args["project_id"], args["name"], args["commit_sha"],
        stats, args["files"], args["chunks"], args["modules"],
    )

    key = f"index-snapshots/{args['project_id']}/{args['job_id']}.json"
    assert stats["archive_key"] == key
    assert "archive_warning" not in stats
    body = json.loads(fake.objects[key]["body"].decode())
    assert body["schema"] == 1
    assert len(body["files"]) == 2


async def test_archive_failure_degrades_to_warning(minio):
    """spec 场景: 索引成功但 MinIO 不可达 → 任务仍 succeeded，stats 含归档 warning。

    这里断的是"归档函数绝不抛异常"——它在管道里排在 _finish 之前，
    只要它不抛，任务就照常走到 succeeded。
    """
    minio(bucket_exists=True, fail_on_put=True)
    args = snapshot_args()
    stats = args["stats"]

    await archive_index_snapshot(
        args["job_id"], args["project_id"], args["name"], args["commit_sha"],
        stats, args["files"], args["chunks"], args["modules"],
    )

    assert "archive_key" not in stats
    assert "产物归档失败" in stats["archive_warning"]
    assert stats["chunks"] == 2          # 原有统计没被破坏


async def test_archive_is_noop_when_storage_disabled(minio_off):
    args = snapshot_args()
    stats = args["stats"]

    await archive_index_snapshot(
        args["job_id"], args["project_id"], args["name"], args["commit_sha"],
        stats, args["files"], args["chunks"], args["modules"],
    )

    assert stats == {"chunks": 2}        # 一个字段都没加


# ---------------- 4.2 报告导出端点 ----------------


async def make_project_with_report(test_db, *, with_report=True) -> uuid.UUID:
    async with test_db() as session:
        project = Project(
            name="mini-shop", git_url="https://example.com/x.git",
            status=ProjectStatus.READY,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        pid = project.id
        if with_report:
            session.add(
                UnderstandingReport(
                    project_id=pid,
                    doc_markdown="# 需求逻辑文档\n正文",
                    feature_map_markdown="# 功能导图\n- 订单",
                    mindmap_mermaid="mindmap",
                    generated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
        return pid


async def test_export_returns_markdown_attachment(api_client, test_db, minio_off):
    """前端并行开发依赖这份契约：状态码、Content-Type、文件名、正文拼接方式。"""
    pid = await make_project_with_report(test_db)

    resp = await api_client.get(f"/projects/{pid}/report/export")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert resp.headers["content-disposition"] == (
        f'attachment; filename="report-{pid}.md"'
    )
    assert resp.text == "# 需求逻辑文档\n正文\n\n# 功能导图\n- 订单"


async def test_export_uploads_to_minio(api_client, test_db, minio):
    fake = minio(bucket_exists=True)
    pid = await make_project_with_report(test_db)

    resp = await api_client.get(f"/projects/{pid}/report/export")

    assert resp.status_code == 200
    assert fake.objects[f"reports/{pid}.md"]["content_type"] == "text/markdown"


async def test_export_still_returns_file_when_minio_fails(api_client, test_db, minio):
    """留档失败不该让用户下不到文件。"""
    minio(bucket_exists=True, fail_on_put=True)
    pid = await make_project_with_report(test_db)

    resp = await api_client.get(f"/projects/{pid}/report/export")

    assert resp.status_code == 200
    assert "需求逻辑文档" in resp.text


async def test_export_404_without_report(api_client, test_db, minio_off):
    pid = await make_project_with_report(test_db, with_report=False)

    resp = await api_client.get(f"/projects/{pid}/report/export")

    assert resp.status_code == 404


async def test_export_404_for_unknown_project(api_client, minio_off):
    resp = await api_client.get(f"/projects/{uuid.uuid4()}/report/export")

    assert resp.status_code == 404


async def test_export_requires_login(anon_client, test_db, minio_off):
    """鉴权与其他项目接口一致（require_user）。"""
    pid = await make_project_with_report(test_db)

    resp = await anon_client.get(f"/projects/{pid}/report/export")

    assert resp.status_code == 401
