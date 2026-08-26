"""容量护栏单测（M14 组 1）。

护栏只拦新建：重索引、删除都必须照常，删完还要立刻腾出槽位。
"""
import shutil
import uuid
from collections import namedtuple

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.tables import IndexJob, Project

DiskUsage = namedtuple("DiskUsage", "total used free")
GB = 1024**3


@pytest.fixture
def disk(monkeypatch):
    """按 GB 造磁盘读数。默认宽裕，用例按需调窄。"""

    def install(free_gb: float, total_gb: float = 59):
        monkeypatch.setattr(
            shutil, "disk_usage",
            lambda _path: DiskUsage(
                total=int(total_gb * GB),
                used=int((total_gb - free_gb) * GB),
                free=int(free_gb * GB),
            ),
        )

    install(41)
    return install


async def seed_projects(test_db, count: int) -> list[uuid.UUID]:
    ids = []
    async with test_db() as session:
        for i in range(count):
            project = Project(name=f"p{i}", git_url=f"https://example.com/{i}.git")
            session.add(project)
            await session.commit()
            await session.refresh(project)
            ids.append(project.id)
    return ids


def payload(name="新项目"):
    return {"name": name, "git_url": "https://example.com/new.git"}


@pytest.fixture
def started_jobs(monkeypatch, test_db):
    """拦下真正的索引启动（重索引用例只关心有没有被容量拦住）。"""
    calls: list[dict] = []

    async def fake_start(project_id, mode="auto", depth="deep"):
        calls.append({"project_id": project_id, "mode": mode, "depth": depth})
        async with test_db() as session:
            job = IndexJob(project_id=project_id, kind=mode)
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    monkeypatch.setattr("app.api.projects.start_index_job", fake_start)
    return calls


# ---------------- GET /meta/capacity ----------------


async def test_capacity_reports_all_six_fields(api_client, test_db, disk, monkeypatch):
    """spec 场景: 容量状态可见——契约六字段，前端按此写死。"""
    monkeypatch.setattr(settings, "project_limit", 8)
    disk(41, total_gb=59)
    await seed_projects(test_db, 3)

    body = (await api_client.get("/meta/capacity")).json()

    assert body == {
        "projects_used": 3,
        "projects_limit": 8,
        "disk_free_gb": 41.0,
        "disk_total_gb": 59.0,
        "accepting": True,
        "reason": "",          # 接受时 reason 必须是空串，前端据此判断是否展示
    }


async def test_capacity_reason_filled_when_slots_full(
    api_client, test_db, disk, monkeypatch
):
    monkeypatch.setattr(settings, "project_limit", 2)
    await seed_projects(test_db, 2)

    body = (await api_client.get("/meta/capacity")).json()

    assert body["accepting"] is False
    assert "项目槽位已满（2/2）" in body["reason"]


async def test_capacity_reason_covers_both_guards(
    api_client, test_db, disk, monkeypatch
):
    """两条都不满足时原因都给——省得用户删完项目才发现磁盘也不够。"""
    monkeypatch.setattr(settings, "project_limit", 1)
    monkeypatch.setattr(settings, "disk_min_free_gb", 5)
    disk(2)
    await seed_projects(test_db, 1)

    body = (await api_client.get("/meta/capacity")).json()

    assert "项目槽位已满" in body["reason"]
    assert "磁盘空间不足" in body["reason"]


async def test_capacity_requires_login(anon_client, disk):
    assert (await anon_client.get("/meta/capacity")).status_code == 401


# ---------------- 槽位护栏边界 ----------------


async def test_creation_allowed_one_slot_below_limit(
    api_client, test_db, disk, monkeypatch
):
    """8 上限、已有 7 个 → 第 8 个必须能建（边界不能差一）。"""
    monkeypatch.setattr(settings, "project_limit", 8)
    await seed_projects(test_db, 7)

    resp = await api_client.post("/projects", json=payload())

    assert resp.status_code == 201
    async with test_db() as session:
        assert len((await session.scalars(select(Project))).all()) == 8


async def test_creation_rejected_at_limit(api_client, test_db, disk, monkeypatch):
    """spec 场景: 槽位满拒绝新建——409 且不产生新项目记录。"""
    monkeypatch.setattr(settings, "project_limit", 8)
    await seed_projects(test_db, 8)

    resp = await api_client.post("/projects", json=payload())

    assert resp.status_code == 409
    assert "项目槽位已满（8/8）" in resp.json()["detail"]
    async with test_db() as session:
        assert len((await session.scalars(select(Project))).all()) == 8


async def test_limit_is_configurable(api_client, test_db, disk, monkeypatch):
    """spec: 上限可经环境变量配置（线上验收就是临时调低到 2 验证拦截）。"""
    monkeypatch.setattr(settings, "project_limit", 2)
    await seed_projects(test_db, 2)

    assert (await api_client.post("/projects", json=payload())).status_code == 409

    monkeypatch.setattr(settings, "project_limit", 3)
    assert (await api_client.post("/projects", json=payload())).status_code == 201


# ---------------- 磁盘护栏 ----------------


async def test_creation_rejected_when_disk_low(api_client, test_db, disk, monkeypatch):
    """spec 场景: 磁盘不足拒绝新建。"""
    monkeypatch.setattr(settings, "project_limit", 8)
    monkeypatch.setattr(settings, "disk_min_free_gb", 5)
    disk(3.2)

    resp = await api_client.post("/projects", json=payload())

    assert resp.status_code == 409
    assert "磁盘空间不足（剩余 3.2G，阈值 5" in resp.json()["detail"]
    async with test_db() as session:
        assert (await session.scalars(select(Project))).all() == []


async def test_disk_exactly_at_threshold_is_rejected(
    api_client, disk, monkeypatch
):
    """D1 的口径是"大于阈值"才收，等于阈值不收。"""
    monkeypatch.setattr(settings, "disk_min_free_gb", 5)
    disk(5)

    assert (await api_client.post("/projects", json=payload())).status_code == 409


async def test_disk_just_above_threshold_is_accepted(api_client, disk, monkeypatch):
    monkeypatch.setattr(settings, "disk_min_free_gb", 5)
    disk(5.1)

    assert (await api_client.post("/projects", json=payload())).status_code == 201


async def test_unreadable_disk_skips_disk_guard(api_client, monkeypatch):
    """量不到磁盘时只放弃兜底那道，槽位主护栏还在——不能因为一次 statvfs 抖动全站拒收。"""

    def boom(_path):
        raise OSError("statvfs failed")

    monkeypatch.setattr(shutil, "disk_usage", boom)

    resp = await api_client.post("/projects", json=payload())

    assert resp.status_code == 201
    body = (await api_client.get("/meta/capacity")).json()
    assert body["disk_total_gb"] == 0      # 0 = 量不到，前端可据此隐藏磁盘段
    assert body["accepting"] is True


# ---------------- 只拦新建：重索引与删除不受限 ----------------


async def test_reindex_not_blocked_when_full(
    api_client, test_db, disk, monkeypatch, started_jobs
):
    """spec 场景: 容量已满时重索引仍正常受理。"""
    monkeypatch.setattr(settings, "project_limit", 2)
    monkeypatch.setattr(settings, "disk_min_free_gb", 5)
    disk(1)                                    # 两道护栏同时不满足
    ids = await seed_projects(test_db, 2)

    resp = await api_client.post(f"/projects/{ids[0]}/index")

    assert resp.status_code == 202
    assert len(started_jobs) == 1


async def test_delete_frees_a_slot(api_client, test_db, disk, monkeypatch):
    """spec 场景: 满额下删掉一个再录入 → 成功。"""
    monkeypatch.setattr(settings, "project_limit", 2)
    ids = await seed_projects(test_db, 2)

    async def noop(_pid):
        return None

    monkeypatch.setattr("app.api.projects.delete_project_graph", noop)

    assert (await api_client.post("/projects", json=payload())).status_code == 409
    assert (await api_client.delete(f"/projects/{ids[0]}")).status_code == 204
    assert (await api_client.get("/meta/capacity")).json()["projects_used"] == 1
    assert (await api_client.post("/projects", json=payload())).status_code == 201


async def test_delete_not_blocked_by_capacity(api_client, test_db, disk, monkeypatch):
    """删除是"腾地方"的动作，任何情况下都不能被容量拦住。"""
    monkeypatch.setattr(settings, "project_limit", 1)
    monkeypatch.setattr(settings, "disk_min_free_gb", 5)
    disk(0.5)
    ids = await seed_projects(test_db, 1)

    async def noop(_pid):
        return None

    monkeypatch.setattr("app.api.projects.delete_project_graph", noop)

    assert (await api_client.delete(f"/projects/{ids[0]}")).status_code == 204
