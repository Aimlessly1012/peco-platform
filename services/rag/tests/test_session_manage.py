"""会话删除与改名（M14+）。

删除靠 FK CASCADE 连消息一起清；别人的会话一律 404（403 会泄露存在性，
与 _owned_session 的既有语义一致）。
"""
import uuid

import pytest

from app.models.tables import Project


async def _make_project_and_session(api_client, test_db) -> tuple[str, str]:
    async with test_db() as s:
        p = Project(name="t", git_url="https://example.com/t.git")
        s.add(p)
        await s.commit()
        await s.refresh(p)
        pid = str(p.id)
    resp = await api_client.post(f"/projects/{pid}/sessions", json={})
    assert resp.status_code == 201
    return pid, resp.json()["id"]



async def test_rename_session(api_client, test_db):
    _, sid = await _make_project_and_session(api_client, test_db)
    resp = await api_client.patch(f"/sessions/{sid}", json={"title": "  接口梳理  "})
    assert resp.status_code == 200
    assert resp.json()["title"] == "接口梳理"  # 前后空白被剥掉



async def test_rename_blank_rejected(api_client, test_db):
    _, sid = await _make_project_and_session(api_client, test_db)
    resp = await api_client.patch(f"/sessions/{sid}", json={"title": "   "})
    assert resp.status_code == 422



async def test_delete_session_gone_from_list(api_client, test_db):
    pid, sid = await _make_project_and_session(api_client, test_db)
    resp = await api_client.delete(f"/sessions/{sid}")
    assert resp.status_code == 204
    listing = await api_client.get(f"/projects/{pid}/sessions")
    assert all(s["id"] != sid for s in listing.json())
    # 已删会话的消息接口 404（存在性一并消失）
    assert (await api_client.get(f"/sessions/{sid}/messages")).status_code == 404



async def test_other_users_session_404(api_client, member_client, test_db):
    """member 碰 admin 的会话：改名/删除都 404，不泄露存在。"""
    _, sid = await _make_project_and_session(api_client, test_db)
    assert (await member_client.patch(f"/sessions/{sid}", json={"title": "x"})).status_code == 404
    assert (await member_client.delete(f"/sessions/{sid}")).status_code == 404



async def test_delete_unknown_404(api_client):
    assert (await api_client.delete(f"/sessions/{uuid.uuid4()}")).status_code == 404
