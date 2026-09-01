"""git bundle 源码主存储（M16 组 3）。

用真实的本地 git 仓库当"远端"，MinIO 用一个目录当假存储——bundle 往返、fetch
增量、D6 容错矩阵都要跑到真的 git 命令上，mock 掉 git 就等于什么都没测。
"""
import uuid
from pathlib import Path

import pytest
from git import Repo

from tests.helpers.repos import init_repo_with as make_repo, write_and_commit as commit

from app.core.config import settings
from app.services.ingest import git_ops
from app.services.ingest.git_ops import (
    GitPullError,
    bundle_key,
    clone_fresh,
    diff_changed_files,
    export_bundle,
    ls_remote_head,
    restore_workdir,
)


# ---------------- 3.1 bundle 往返 ----------------


def test_bundle_key_is_project_scoped_and_stable():
    """固定 key 覆盖写（D3）：同项目永远同一个 key，不按 commit 攒历史。"""
    assert bundle_key("p1") == "repo-bundles/p1.bundle"
    assert bundle_key("p1") == bundle_key("p1")


def test_export_then_restore_roundtrip(tmp_path, origin, store):
    """spec 场景: bundle 可被 clone 直接恢复出完整仓库。"""
    work = tmp_path / "w1"
    clone_fresh(origin.url, work)
    assert export_bundle("p1", work) == "repo-bundles/p1.bundle"
    assert store["uploaded"][0][1] == "application/x-git-bundle"

    restored = tmp_path / "w2"
    restored.mkdir()
    sha, source = restore_workdir("p1", origin.url, restored)

    assert source == "bundle"
    assert sha == origin.head
    # 完整历史：两个提交都在（bundle 的立身之本）
    assert len(list(Repo(restored).iter_commits())) == 2
    assert (restored / "a.py").exists() and (restored / "b.py").exists()


def test_restore_then_fetch_picks_up_new_commits(tmp_path, origin, store):
    """spec 场景: bundle 恢复 + fetch 增量后，增量索引的 git diff 判定照常生效。"""
    work = tmp_path / "w1"
    clone_fresh(origin.url, work)
    export_bundle("p1", work)

    # bundle 打完之后远端又有了新提交
    third = commit(origin.repo, origin.path, {"c.py": "def c():\n    return 3\n"}, "third")

    restored = tmp_path / "w2"
    restored.mkdir()
    sha, source = restore_workdir("p1", origin.url, restored)

    assert source == "bundle"
    assert sha == third
    # 关键：基准 commit 仍在历史里，diff 拿得到——增量语义被保全
    changed = diff_changed_files(restored, origin.head, third)
    assert changed.added == ["c.py"]
    assert changed.total() == 1


def test_clone_fresh_keeps_full_history(tmp_path, origin):
    """clone 不能用 depth=1。

    浅克隆做出来的 bundle 是坏的：`git bundle create --all` 照样退出 0、照样产出
    文件，但从它 clone 时报 "remote did not send all necessary objects"——
    归档看着成功、恢复时才炸。这条断言就是防止有人把 depth=1 加回去。
    """
    work = tmp_path / "w"
    clone_fresh(origin.url, work)

    assert len(list(Repo(work).iter_commits())) == 2
    assert not (work / ".git" / "shallow").exists()


def test_restored_workdir_keeps_no_token_on_disk(tmp_path, origin, store):
    """token 不许落盘——恢复后 remote url 必须是原始无凭据版本。"""
    work = tmp_path / "w1"
    clone_fresh(origin.url, work)
    export_bundle("p1", work)

    restored = tmp_path / "w2"
    restored.mkdir()
    restore_workdir("p1", origin.url, restored, token="s3cret")

    config = (restored / ".git" / "config").read_text()
    assert "s3cret" not in config
    assert Repo(restored).remotes.origin.url == origin.url
    # 顺带钉住 _auth_url 的护栏：本地路径没有可注入凭据的位置，原样返回而不是
    # 拼出 "//oauth2:tok@None/path" 这种废 URL
    assert git_ops._auth_url(origin.url, "s3cret") == origin.url


# ---------------- 3.2 容错矩阵（D6）----------------


def test_missing_bundle_falls_back_to_clone(tmp_path, origin, store):
    """首次索引：MinIO 里根本没有这个项目的 bundle。"""
    work = tmp_path / "w"
    work.mkdir()

    sha, source = restore_workdir("never-indexed", origin.url, work)

    assert source == "clone"
    assert sha == origin.head


def test_corrupt_bundle_falls_back_to_clone(tmp_path, origin, store):
    """bundle 文件损坏（半截上传、磁盘坏道）→ clone 远端，任务照常。"""
    store["path_of"](bundle_key("p1")).write_bytes(b"not a git bundle at all")
    work = tmp_path / "w"
    work.mkdir()

    sha, source = restore_workdir("p1", origin.url, work)

    assert source == "clone"
    assert sha == origin.head
    assert len(list(Repo(work).iter_commits())) == 2


def test_download_error_falls_back_to_clone(tmp_path, origin, store):
    """MinIO 整个不可达 → clone 远端。"""
    store["download_raises"] = True
    work = tmp_path / "w"
    work.mkdir()

    sha, source = restore_workdir("p1", origin.url, work)

    assert source == "clone"
    assert sha == origin.head


def test_storage_disabled_falls_back_to_clone(tmp_path, origin, store):
    """没配 MinIO 的部署形态：整层 no-op，直接 clone。"""
    store["enabled"] = False
    work = tmp_path / "w"
    work.mkdir()

    assert restore_workdir("p1", origin.url, work)[1] == "clone"


def test_fetch_failure_falls_back_to_clone(tmp_path, origin, store):
    """bundle 是好的，但远端连不上（token 失效/仓库搬家）→ 退回 clone 远端。

    这里 clone 也会失败，于是任务以带中文文案的 GitPullError 结束——
    "取码这一步"允许失败的唯一情形就是它：远端真的拿不到。
    """
    work = tmp_path / "w1"
    clone_fresh(origin.url, work)
    export_bundle("p1", work)

    restored = tmp_path / "w2"
    restored.mkdir()
    with pytest.raises(GitPullError):
        restore_workdir("p1", str(tmp_path / "gone"), restored)


def test_fetch_failure_still_indexes_when_remote_moved(tmp_path, origin, store):
    """bundle 对应的远端换了地址，但新地址可用 → clone 新远端成功。"""
    work = tmp_path / "w1"
    clone_fresh(origin.url, work)
    export_bundle("p1", work)

    moved = tmp_path / "moved"
    make_repo(moved, {"z.py": "def z():\n    return 0\n"})
    restored = tmp_path / "w2"
    restored.mkdir()

    sha, source = restore_workdir("p1", str(moved), restored)

    assert sha == Repo(moved).head.commit.hexsha
    assert (restored / "z.py").exists()


async def test_upload_failure_is_only_a_warning(tmp_path, origin, store, monkeypatch):
    """spec: bundle 上传失败降级为 warning，不影响索引任务成败。"""
    from app.services.ingest import pipeline

    monkeypatch.setattr(pipeline, "storage_enabled", lambda: True)
    store["upload_raises"] = True
    work = tmp_path / "w"
    clone_fresh(origin.url, work)
    stats = {"chunks": 3}

    await pipeline.archive_repo_bundle("p1", work, stats)   # 不抛

    assert "repo_bundle_key" not in stats
    assert "源码 bundle 归档失败" in stats["repo_bundle_warning"]
    assert stats["chunks"] == 3


async def test_archive_records_key_on_success(tmp_path, origin, store, monkeypatch):
    from app.services.ingest import pipeline

    monkeypatch.setattr(pipeline, "storage_enabled", lambda: True)
    work = tmp_path / "w"
    clone_fresh(origin.url, work)
    stats = {}

    await pipeline.archive_repo_bundle("p1", work, stats)

    assert stats["repo_bundle_key"] == "repo-bundles/p1.bundle"
    assert store["path_of"]("repo-bundles/p1.bundle").exists()


async def test_archive_is_noop_when_storage_disabled(tmp_path, origin, store, monkeypatch):
    from app.services.ingest import pipeline

    monkeypatch.setattr(pipeline, "storage_enabled", lambda: False)
    work = tmp_path / "w"
    clone_fresh(origin.url, work)
    stats = {}

    await pipeline.archive_repo_bundle("p1", work, stats)

    assert stats == {}


async def test_broken_repo_archive_is_warning(tmp_path, store, monkeypatch):
    """工作区不是 git 仓库（理论上不该发生）→ 只记 warning。"""
    from app.services.ingest import pipeline

    monkeypatch.setattr(pipeline, "storage_enabled", lambda: True)
    stats = {}

    await pipeline.archive_repo_bundle("p1", tmp_path / "not-a-repo", stats)

    assert "repo_bundle_warning" in stats


# ---------------- 3.3 ls-remote 秒回 ----------------


def test_ls_remote_head_reads_remote_sha(origin):
    assert ls_remote_head(origin.url) == origin.head


def test_ls_remote_head_with_explicit_branch(origin):
    branch = origin.repo.active_branch.name
    assert ls_remote_head(origin.url, branch) == origin.head


def test_ls_remote_head_returns_none_on_failure(tmp_path):
    """取不到就返回 None——网络抖一下不该被当成"索引失败"。"""
    assert ls_remote_head(str(tmp_path / "nope")) is None


def test_ls_remote_head_returns_none_for_missing_branch(origin):
    assert ls_remote_head(origin.url, "no-such-branch") is None


@pytest.fixture
def meta_ok(monkeypatch):
    """图里有该项目、嵌入模型也对得上。"""
    async def load(_pid):
        return {"embedding_model": settings.embedding_model,
                "embedding_dim": settings.embedding_dim}

    monkeypatch.setattr(
        "app.services.ingest.pipeline.load_project_index_meta", load
    )


DEFAULTS = dict(mode="auto", depth="deep", current_depth="deep",
                last_indexed_commit="sha1", remote_head="sha1", project_id="p")


async def test_remote_unchanged_true_when_everything_matches(meta_ok):
    from app.services.ingest.pipeline import remote_unchanged

    assert await remote_unchanged(**DEFAULTS) is True


@pytest.mark.parametrize(
    "override,why",
    [
        ({"remote_head": "sha2"}, "远端有新提交"),
        ({"remote_head": None}, "ls-remote 没取到"),
        ({"last_indexed_commit": None}, "首次索引"),
        ({"mode": "full"}, "强制全量是逃生门，不能被秒回吃掉"),
        ({"depth": "deep", "current_depth": "fast"}, "fast→deep 补跑要全量"),
    ],
)
async def test_remote_unchanged_false_cases(meta_ok, override, why):
    from app.services.ingest.pipeline import remote_unchanged

    assert await remote_unchanged(**{**DEFAULTS, **override}) is False, why


async def test_remote_unchanged_false_when_graph_empty(monkeypatch):
    """图被清理过：代码没变也必须重建，否则项目永远索引不回来。"""
    from app.services.ingest.pipeline import remote_unchanged

    async def load(_pid):
        return {}

    monkeypatch.setattr("app.services.ingest.pipeline.load_project_index_meta", load)

    assert await remote_unchanged(**DEFAULTS) is False


async def test_remote_unchanged_false_when_embedding_model_changed(monkeypatch):
    """换了嵌入模型必须全量重嵌入——存量向量和新向量不在一个空间。"""
    from app.services.ingest.pipeline import remote_unchanged

    async def load(_pid):
        return {"embedding_model": "old-model", "embedding_dim": settings.embedding_dim}

    monkeypatch.setattr("app.services.ingest.pipeline.load_project_index_meta", load)

    assert await remote_unchanged(**DEFAULTS) is False


async def test_fast_return_touches_neither_storage_nor_workdir(
    test_db, tmp_path, monkeypatch, meta_ok
):
    """spec 场景: 无变化不动存储——不拉 bundle、不建工作区、秒级 succeeded。"""
    from app.models.tables import IndexJob, Project
    from app.services.ingest import pipeline

    monkeypatch.setattr(settings, "repos_dir", tmp_path / "repos")
    monkeypatch.setattr(pipeline, "ls_remote_head", lambda *a, **k: "sha-same")

    def must_not_run(*_a, **_k):
        raise AssertionError("秒回路径不该建工作区/拉 bundle")

    monkeypatch.setattr(pipeline, "restore_workdir", must_not_run)
    monkeypatch.setattr(pipeline, "export_bundle", must_not_run)

    async with test_db() as session:
        project = Project(name="p", git_url="https://example.com/x.git",
                          last_indexed_commit="sha-same")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        job = IndexJob(project_id=project.id, kind="auto")
        session.add(job)
        await session.commit()
        await session.refresh(job)
        pid, job_id = project.id, job.id

    await pipeline.run_index_job(job_id, pid, "auto", "deep")

    async with test_db() as session:
        done = await session.get(IndexJob, job_id)
        assert done.status == "succeeded", done.error_text
        assert done.stats_json == {
            "mode": "incremental", "no_changes": True,
            "no_changes_source": "ls-remote",
        }
    # 连临时根都没必要建出东西来
    assert not any((tmp_path / "repos").glob("*")) if (tmp_path / "repos").exists() else True


async def test_workdir_is_cleaned_up_even_on_failure(
    test_db, tmp_path, monkeypatch
):
    """D4：成败都清。本地盘不再是源码的持久层，留下来只会白占磁盘。"""
    from app.models.tables import IndexJob, Project
    from app.services.ingest import pipeline

    repos = tmp_path / "repos"
    monkeypatch.setattr(settings, "repos_dir", repos)
    monkeypatch.setattr(pipeline, "ls_remote_head", lambda *a, **k: "sha-new")

    def boom(*_a, **_k):
        raise RuntimeError("取码炸了")

    monkeypatch.setattr(pipeline, "restore_workdir", boom)

    async with test_db() as session:
        project = Project(name="p", git_url="https://example.com/x.git")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        job = IndexJob(project_id=project.id, kind="auto")
        session.add(job)
        await session.commit()
        await session.refresh(job)
        pid, job_id = project.id, job.id

    await pipeline.run_index_job(job_id, pid, "auto", "deep")

    async with test_db() as session:
        assert (await session.get(IndexJob, job_id)).status == "failed"
    assert list(repos.iterdir()) == [], "失败路径也必须把临时工作区清干净"


# ---------------- 残留工作区清扫（OOM kill 后 finally 不会执行）----------------


def test_cleanup_removes_stale_workdirs(tmp_path, monkeypatch):
    """worker 被 OOM kill 时 finally 不执行，残留目录只能靠下次启动扫掉。"""
    from app.services.ingest.pipeline import cleanup_stale_workdirs

    repos = tmp_path / "repos"
    repos.mkdir()
    (repos / f"{uuid.uuid4()}-abc").mkdir()
    (repos / f"{uuid.uuid4()}-def").mkdir()
    (repos / "keep.txt").write_text("不是目录，别动")
    monkeypatch.setattr(settings, "repos_dir", repos)

    assert cleanup_stale_workdirs() == 2
    assert [p.name for p in repos.iterdir()] == ["keep.txt"]


def test_cleanup_is_safe_on_missing_root(tmp_path, monkeypatch):
    from app.services.ingest.pipeline import cleanup_stale_workdirs

    monkeypatch.setattr(settings, "repos_dir", tmp_path / "nope")

    assert cleanup_stale_workdirs() == 0
