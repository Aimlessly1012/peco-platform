"""git 仓库相关的共享测试夹具（M17 1.5：从 test_incremental.py 下沉）。"""
import shutil
from pathlib import Path

from git import Repo

FIXTURE_REPO = Path(__file__).parent.parent / "fixtures" / "mini_repo"


def make_repo(path: Path) -> Repo:
    repo = Repo.init(path)
    repo.config_writer().set_value("user", "name", "test").release()
    repo.config_writer().set_value("user", "email", "test@example.com").release()
    return repo


def commit_all(repo: Repo, message: str) -> str:
    repo.git.add(A=True)
    repo.index.commit(message)
    return repo.head.commit.hexsha


def existing(paths: list[str]) -> dict:
    """图中已有的 File 元数据（增量 plan 用）。"""
    from app.services.ingest.graph_writer import FileInfo

    return {
        p: FileInfo(path=p, language="python", content_hash="h", summary="s", imports=[])
        for p in paths
    }


def make_source_repo(path: Path) -> tuple[Repo, str]:
    """把 mini_repo 复制成一个真实 git 仓库作为"远端"。"""
    shutil.copytree(FIXTURE_REPO, path, dirs_exist_ok=True)
    repo = make_repo(path)
    return repo, commit_all(repo, "init")


def write_and_commit(repo: Repo, path: Path, files: dict[str, str], message: str) -> str:
    """往仓库写一批文件并提交，返回 commit sha。"""
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return commit_all(repo, message)


def init_repo_with(path: Path, files: dict[str, str], message: str = "init") -> str:
    path.mkdir(parents=True, exist_ok=True)
    return write_and_commit(make_repo(path), path, files, message)
