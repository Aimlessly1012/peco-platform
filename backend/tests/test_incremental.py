"""增量重索引的 diff 与计划单测（M4 B4/B6）。

diff 解析用真实 git 仓库（tmp_path），不 mock git——改名/删除这类语义 mock 不出来。
"""
from pathlib import Path

import pytest
from git import Repo

from app.services.ingest.git_ops import (
    ChangedFiles,
    GitDiffError,
    diff_changed_files,
    head_sha,
    parse_name_status,
)
from app.services.ingest.pipeline import MODE_AUTO, MODE_FULL, build_index_plan


def make_repo(path: Path) -> Repo:
    repo = Repo.init(path)
    repo.config_writer().set_value("user", "name", "test").release()
    repo.config_writer().set_value("user", "email", "test@example.com").release()
    return repo


def commit_all(repo: Repo, message: str) -> str:
    repo.git.add(A=True)
    repo.index.commit(message)
    return repo.head.commit.hexsha


# ---------------- name-status 解析 ----------------


def test_parse_name_status_basic():
    raw = "M\0src/a.py\0A\0src/b.py\0D\0src/c.py\0"
    changed = parse_name_status(raw)

    assert changed.modified == ["src/a.py"]
    assert changed.added == ["src/b.py"]
    assert changed.deleted == ["src/c.py"]
    assert changed.total() == 3
    assert changed.touched == ["src/b.py", "src/a.py"]


def test_parse_name_status_rename_splits_into_delete_and_add():
    """设计 D1：R 视为 D+A——改名后旧节点必须从图里消失。"""
    raw = "R100\0old/path.py\0new/path.py\0M\0other.py\0"
    changed = parse_name_status(raw)

    assert changed.deleted == ["old/path.py"]
    assert changed.added == ["new/path.py"]
    assert changed.modified == ["other.py"]


def test_parse_name_status_edge_cases():
    assert parse_name_status("").is_empty()
    assert parse_name_status("\0\0").is_empty()
    # 截断输出不得抛异常（宁可少算变更也不能让整个任务炸）
    assert parse_name_status("M\0").is_empty()
    assert parse_name_status("R100\0only-old\0").is_empty()
    # T（类型变更）按修改处理
    assert parse_name_status("T\0link.py\0").modified == ["link.py"]


# ---------------- 真实仓库 diff ----------------


def test_diff_changed_files_on_real_repo(tmp_path):
    repo = make_repo(tmp_path)
    (tmp_path / "keep.py").write_text("x = 1\n")
    (tmp_path / "edit.py").write_text("y = 1\n")
    (tmp_path / "gone.py").write_text("z = 1\n")
    (tmp_path / "old_name.py").write_text("w = 1\n")
    first = commit_all(repo, "init")

    (tmp_path / "edit.py").write_text("y = 2\n")
    (tmp_path / "gone.py").unlink()
    (tmp_path / "added.py").write_text("n = 1\n")
    repo.git.mv("old_name.py", "new_name.py")
    second = commit_all(repo, "change")

    changed = diff_changed_files(tmp_path, first, second)

    assert set(changed.modified) == {"edit.py"}
    assert set(changed.added) == {"added.py", "new_name.py"}
    assert set(changed.deleted) == {"gone.py", "old_name.py"}
    assert "keep.py" not in changed.touched + changed.deleted


def test_diff_same_commit_is_empty(tmp_path):
    repo = make_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    sha = commit_all(repo, "init")

    assert diff_changed_files(tmp_path, sha, sha).is_empty()


def test_diff_without_git_dir_raises(tmp_path):
    with pytest.raises(GitDiffError, match="本地仓库副本"):
        diff_changed_files(tmp_path, "aaa", "bbb")


def test_diff_with_unknown_commit_raises(tmp_path):
    repo = make_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    sha = commit_all(repo, "init")

    with pytest.raises(GitDiffError):
        diff_changed_files(tmp_path, "0" * 40, sha)


def test_head_sha(tmp_path):
    assert head_sha(tmp_path) is None
    repo = make_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    sha = commit_all(repo, "init")
    assert head_sha(tmp_path) == sha


# ---------------- auto 判定与回退（设计 D3） ----------------


@pytest.fixture
def graph_stub(monkeypatch):
    """打桩图读回，使计划构建无需 Neo4j。

    嵌入模型默认与当前配置一致——本文件测的是 diff 与回退判定，
    换模型的防护另见 test_embed_cache_key.py。
    """
    from app.core.config import settings

    state = {
        "files": {},
        "chunks": [],
        "meta": {
            "embedding_model": settings.embedding_model,
            "embedding_dim": settings.embedding_dim,
        },
    }

    async def fake_files(pid):
        return dict(state["files"])

    async def fake_chunks(pid, paths):
        return [c for c in state["chunks"] if c.file_path in paths]

    async def fake_meta(pid):
        return dict(state["meta"])

    monkeypatch.setattr("app.services.ingest.pipeline.load_file_metadata", fake_files)
    monkeypatch.setattr("app.services.ingest.pipeline.load_chunk_metadata", fake_chunks)
    monkeypatch.setattr("app.services.ingest.pipeline.load_project_index_meta", fake_meta)
    return state


def existing(paths: list[str]) -> dict:
    from app.services.ingest.graph_writer import FileInfo

    return {
        p: FileInfo(path=p, language="python", content_hash="h", summary="s", imports=[])
        for p in paths
    }


async def test_plan_full_mode_never_diffs(tmp_path, graph_stub):
    plan = await build_index_plan(
        MODE_FULL, project_id="p", repo_dir=tmp_path,
        last_indexed_commit="abc", commit_sha="def",
        walk_files=[Path("a.py")],
    )
    assert plan.mode == MODE_FULL
    assert plan.fallback_reason is None      # 显式 full 不是"回退"
    assert plan.parse_paths == [Path("a.py")]


@pytest.mark.parametrize(
    "last_commit,expect_reason",
    [(None, "首次索引"), ("", "首次索引")],
)
async def test_plan_falls_back_without_baseline(tmp_path, graph_stub, last_commit, expect_reason):
    plan = await build_index_plan(
        MODE_AUTO, project_id="p", repo_dir=tmp_path,
        last_indexed_commit=last_commit, commit_sha="def",
        walk_files=[Path("a.py")],
    )
    assert plan.mode == MODE_FULL
    assert expect_reason in plan.fallback_reason


async def test_plan_falls_back_without_local_copy(tmp_path, graph_stub):
    plan = await build_index_plan(
        MODE_AUTO, project_id="p", repo_dir=tmp_path / "missing",
        last_indexed_commit="abc", commit_sha="def", walk_files=[],
    )
    assert plan.mode == MODE_FULL
    assert "本地仓库副本" in plan.fallback_reason


async def test_plan_falls_back_when_graph_empty(tmp_path, graph_stub):
    """图被清空但 commit 没变时不能秒返，否则留下空图还报成功。"""
    repo = make_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    first = commit_all(repo, "init")
    (tmp_path / "a.py").write_text("x = 2\n")
    second = commit_all(repo, "change")
    graph_stub["files"] = {}

    plan = await build_index_plan(
        MODE_AUTO, project_id="p", repo_dir=tmp_path,
        last_indexed_commit=first, commit_sha=second,
        walk_files=[Path("a.py")],
    )
    assert plan.mode == MODE_FULL
    assert "图中无该项目数据" in plan.fallback_reason


async def test_plan_no_changes(tmp_path, graph_stub):
    repo = make_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    sha = commit_all(repo, "init")
    graph_stub["files"] = existing(["a.py"])

    plan = await build_index_plan(
        MODE_AUTO, project_id="p", repo_dir=tmp_path,
        last_indexed_commit=sha, commit_sha=sha, walk_files=[Path("a.py")],
    )
    assert plan.no_changes is True
    assert plan.is_incremental


async def test_plan_incremental_splits_work(tmp_path, graph_stub):
    repo = make_repo(tmp_path)
    for name in ("keep.py", "edit.py", "gone.py"):
        (tmp_path / name).write_text("x = 1\n")
    first = commit_all(repo, "init")
    (tmp_path / "edit.py").write_text("x = 2\n")
    (tmp_path / "gone.py").unlink()
    (tmp_path / "added.py").write_text("y = 1\n")
    second = commit_all(repo, "change")

    graph_stub["files"] = existing(["keep.py", "edit.py", "gone.py"])
    plan = await build_index_plan(
        MODE_AUTO, project_id="p", repo_dir=tmp_path,
        last_indexed_commit=first, commit_sha=second,
        walk_files=[Path("keep.py"), Path("edit.py"), Path("added.py")],
    )

    assert plan.is_incremental
    assert {str(p) for p in plan.parse_paths} == {"edit.py", "added.py"}
    assert set(plan.deleted_paths) == {"gone.py", "edit.py"}  # 改的也要先删旧子图
    assert set(plan.reused_files) == {"keep.py"}
    assert plan.changed_total == 3


async def test_plan_ignores_unparseable_changed_files(tmp_path, graph_stub):
    """改 README 不该触发任何重解析（它不在 walk 结果里）。"""
    repo = make_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "README.md").write_text("# doc\n")
    first = commit_all(repo, "init")
    (tmp_path / "README.md").write_text("# doc changed\n")
    second = commit_all(repo, "docs")

    graph_stub["files"] = existing(["a.py"])
    plan = await build_index_plan(
        MODE_AUTO, project_id="p", repo_dir=tmp_path,
        last_indexed_commit=first, commit_sha=second, walk_files=[Path("a.py")],
    )

    assert plan.is_incremental
    assert plan.parse_paths == []
    assert plan.deleted_paths == []
    assert set(plan.reused_files) == {"a.py"}


async def test_changed_files_helpers():
    changed = ChangedFiles(added=["a"], modified=["b"], deleted=["c"])
    assert changed.total() == 3
    assert changed.touched == ["a", "b"]
    assert not changed.is_empty()
    assert ChangedFiles().is_empty()


# ---------------- API mode 参数（M4 BREAKING：默认 full → auto） ----------------


@pytest.fixture
def started_jobs(monkeypatch, test_db):
    """拦下真正的索引启动，只记录调用参数。"""
    from app.models.tables import IndexJob

    calls: list[dict] = []

    async def fake_start(project_id, mode="auto", depth="deep"):
        calls.append({"project_id": project_id, "mode": mode, "depth": depth})
        if calls[-1].get("blocked"):
            return None
        async with test_db() as session:
            job = IndexJob(project_id=project_id, kind=mode)
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    monkeypatch.setattr("app.api.projects.start_index_job", fake_start)
    return calls


async def _project(test_db):
    from app.models.tables import Project

    async with test_db() as session:
        project = Project(name="p", git_url="https://example.com/x.git")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project.id


async def test_index_defaults_to_auto(api_client, test_db, started_jobs):
    pid = await _project(test_db)
    resp = await api_client.post(f"/projects/{pid}/index")

    assert resp.status_code == 202
    assert started_jobs[0]["mode"] == MODE_AUTO


async def test_index_accepts_full_mode(api_client, test_db, started_jobs):
    pid = await _project(test_db)
    resp = await api_client.post(f"/projects/{pid}/index?mode=full")

    assert resp.status_code == 202
    assert started_jobs[0]["mode"] == MODE_FULL


async def test_index_rejects_unknown_mode(api_client, test_db, started_jobs):
    pid = await _project(test_db)
    resp = await api_client.post(f"/projects/{pid}/index?mode=turbo")

    assert resp.status_code == 422
    assert started_jobs == []  # 非法参数不得启动任务


async def test_index_conflict_semantics_unchanged(api_client, test_db, monkeypatch):
    """spec 场景: 已有 running 任务时仍返回 409（mode 参数不改变这个语义）。"""
    async def fake_start(project_id, mode="auto", depth="deep"):
        return None

    monkeypatch.setattr("app.api.projects.start_index_job", fake_start)
    pid = await _project(test_db)

    resp = await api_client.post(f"/projects/{pid}/index?mode=full")
    assert resp.status_code == 409
    assert "已有索引任务" in resp.json()["detail"]


async def test_index_unknown_project_404(api_client, test_db, started_jobs):
    import uuid as uuid_module

    resp = await api_client.post(f"/projects/{uuid_module.uuid4()}/index")
    assert resp.status_code == 404
    assert started_jobs == []
