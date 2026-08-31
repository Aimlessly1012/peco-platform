"""向量缓存键与换模型防护（M4 B15）。

背景：embed_key 原本只 hash 嵌入文本，切换嵌入模型（DashScope text-embedding-v3 →
本地 Ollama bge-m3，两者都是 1024 维）后重索引会复用旧模型向量，图里混两个向量空间。
维度相同，ensure_vector_index 的维度校验拦不住，只能靠缓存键与 auto 判定。
"""
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.ingest.pipeline import MODE_AUTO, build_index_plan, embed_cache_key
from tests.helpers.repos import commit_all, existing, make_repo

TEXT = "[项目: shop | 模块: orders]\ndef create_order(): ..."


def test_key_is_stable_for_same_config():
    assert embed_cache_key(TEXT) == embed_cache_key(TEXT)


def test_key_changes_with_embedding_model(monkeypatch):
    """同一段文本，换模型必须换键——否则旧向量会被复用。"""
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-v3")
    dashscope_key = embed_cache_key(TEXT)

    monkeypatch.setattr(settings, "embedding_model", "bge-m3")
    ollama_key = embed_cache_key(TEXT)

    assert dashscope_key != ollama_key


def test_key_changes_with_dimension(monkeypatch):
    monkeypatch.setattr(settings, "embedding_model", "bge-m3")
    monkeypatch.setattr(settings, "embedding_dim", 1024)
    key_1024 = embed_cache_key(TEXT)

    monkeypatch.setattr(settings, "embedding_dim", 768)
    assert embed_cache_key(TEXT) != key_1024


def test_key_still_changes_with_text(monkeypatch):
    monkeypatch.setattr(settings, "embedding_model", "bge-m3")
    assert embed_cache_key(TEXT) != embed_cache_key(TEXT + "  # 改了一行")


def test_model_name_is_not_merely_concatenated(monkeypatch):
    """'a' + ':b:text' 与 'a:b' + ':text' 不能撞键（分隔符位置歧义）。"""
    monkeypatch.setattr(settings, "embedding_model", "a")
    monkeypatch.setattr(settings, "embedding_dim", 1024)
    first = embed_cache_key(TEXT)

    monkeypatch.setattr(settings, "embedding_model", "a:1024")
    monkeypatch.setattr(settings, "embedding_dim", 1024)
    assert embed_cache_key(TEXT) != first


# ---------------- auto 判定：换模型强制全量 ----------------


@pytest.fixture
def plan_stubs(monkeypatch):
    state = {"files": existing(["a.py"]), "meta": {}, "chunks": []}

    async def fake_files(pid):
        return dict(state["files"])

    async def fake_meta(pid):
        return dict(state["meta"])

    async def fake_chunks(pid, paths):
        return []

    monkeypatch.setattr("app.services.ingest.pipeline.load_file_metadata", fake_files)
    monkeypatch.setattr(
        "app.services.ingest.pipeline.load_project_index_meta", fake_meta
    )
    monkeypatch.setattr("app.services.ingest.pipeline.load_chunk_metadata", fake_chunks)
    return state


@pytest.fixture
def changed_repo(tmp_path):
    """一个有两次提交的仓库，第二次改了 a.py。"""
    repo = make_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    first = commit_all(repo, "init")
    (tmp_path / "a.py").write_text("x = 2\n")
    second = commit_all(repo, "change")
    return tmp_path, first, second


async def _plan(repo_path, first, second):
    return await build_index_plan(
        MODE_AUTO, project_id="p", repo_dir=repo_path,
        last_indexed_commit=first, commit_sha=second,
        walk_files=[Path("a.py")],
    )


async def test_auto_stays_incremental_when_model_unchanged(
    plan_stubs, changed_repo, monkeypatch
):
    monkeypatch.setattr(settings, "embedding_model", "bge-m3")
    monkeypatch.setattr(settings, "embedding_dim", 1024)
    plan_stubs["meta"] = {"embedding_model": "bge-m3", "embedding_dim": 1024}

    plan = await _plan(*changed_repo)

    assert plan.is_incremental
    assert plan.fallback_reason is None


async def test_auto_forces_full_when_model_changed(plan_stubs, changed_repo, monkeypatch):
    """图里是 DashScope 向量、当前配置是 Ollama → 必须全量重嵌入。"""
    monkeypatch.setattr(settings, "embedding_model", "bge-m3")
    monkeypatch.setattr(settings, "embedding_dim", 1024)
    plan_stubs["meta"] = {"embedding_model": "text-embedding-v3", "embedding_dim": 1024}

    plan = await _plan(*changed_repo)

    assert plan.mode == "full"
    assert plan.fallback_reason == "embedding_model_changed"


async def test_auto_forces_full_when_dim_changed(plan_stubs, changed_repo, monkeypatch):
    monkeypatch.setattr(settings, "embedding_model", "bge-m3")
    monkeypatch.setattr(settings, "embedding_dim", 1024)
    plan_stubs["meta"] = {"embedding_model": "bge-m3", "embedding_dim": 768}

    plan = await _plan(*changed_repo)

    assert plan.fallback_reason == "embedding_model_changed"


async def test_auto_forces_full_for_legacy_projects(plan_stubs, changed_repo, monkeypatch):
    """M4 之前的 Project 节点没有 embedding_model 属性——无从判断旧向量出处，按变化处理。"""
    monkeypatch.setattr(settings, "embedding_model", "bge-m3")
    monkeypatch.setattr(settings, "embedding_dim", 1024)
    plan_stubs["meta"] = {}

    plan = await _plan(*changed_repo)

    assert plan.mode == "full"
    assert plan.fallback_reason == "embedding_model_changed"


async def test_no_changes_still_short_circuits_when_model_matches(
    plan_stubs, tmp_path, monkeypatch
):
    """模型没变、也没有代码变更 → 仍然秒返，不被本防护误伤。"""
    monkeypatch.setattr(settings, "embedding_model", "bge-m3")
    monkeypatch.setattr(settings, "embedding_dim", 1024)
    plan_stubs["meta"] = {"embedding_model": "bge-m3", "embedding_dim": 1024}

    repo = make_repo(tmp_path)
    (tmp_path / "a.py").write_text("x = 1\n")
    sha = commit_all(repo, "init")

    plan = await build_index_plan(
        MODE_AUTO, project_id="p", repo_dir=tmp_path,
        last_indexed_commit=sha, commit_sha=sha, walk_files=[Path("a.py")],
    )
    assert plan.no_changes is True
