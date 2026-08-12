"""仓库拉取与变更集：clone / fetch+reset、token 认证、增量 diff（错误文案不泄露 token）。"""
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from git import GitCommandError, Repo


class GitPullError(Exception):
    """携带可读中文错误信息，保证不含 token。"""


class GitDiffError(Exception):
    """diff 不可用（旧 commit 已被 gc、仓库非 git 等）——调用方据此回退全量。"""


@dataclass
class ChangedFiles:
    """一次 diff 的变更集。改名（R）拆成 deleted + added（设计 D1）。"""

    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def touched(self) -> list[str]:
        """需要重新解析的文件（新增 + 修改）。"""
        return self.added + self.modified

    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.deleted)

    def total(self) -> int:
        return len(self.added) + len(self.modified) + len(self.deleted)


def _auth_url(git_url: str, token: str | None) -> str:
    if not token:
        return git_url
    parsed = urlparse(git_url)
    # GitLab/GitHub 通用：oauth2:<token>@host
    netloc = f"oauth2:{token}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _sanitize(message: str, token: str | None) -> str:
    if token:
        message = message.replace(token, "***")
    # 兜底：清除 URL 中的任何 userinfo
    return re.sub(r"//[^/@\s]+@", "//***@", message)


def pull_repo(
    git_url: str, dest: Path, token: str | None = None, branch: str | None = None
) -> str:
    """clone 或 fetch+reset 仓库到 dest，返回 HEAD commit sha。"""
    url = _auth_url(git_url, token)
    try:
        if (dest / ".git").exists():
            repo = Repo(dest)
            with repo.git.custom_environment(GIT_TERMINAL_PROMPT="0"):
                repo.remotes.origin.set_url(url)
                repo.remotes.origin.fetch(prune=True)
                target = branch or _default_branch(repo)
                repo.git.checkout(target)
                repo.git.reset("--hard", f"origin/{target}")
        else:
            if dest.exists():
                shutil.rmtree(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            kwargs = {"branch": branch} if branch else {}
            repo = Repo.clone_from(
                url, dest, depth=1, env={"GIT_TERMINAL_PROMPT": "0"}, **kwargs
            )
        # 存储的 remote url 还原为无 token 版本，避免密文落盘
        repo.remotes.origin.set_url(git_url)
        return repo.head.commit.hexsha
    except GitCommandError as e:
        detail = _sanitize(str(e), token)
        if "Authentication failed" in detail or "could not read Username" in detail or "403" in detail:
            raise GitPullError("仓库认证失败：请检查 token 是否有效、是否有该仓库读取权限") from e
        if "not found" in detail.lower() or "404" in detail:
            raise GitPullError("仓库不存在或无权访问：请检查 git url") from e
        if "Could not resolve host" in detail:
            raise GitPullError("网络错误：无法解析仓库主机") from e
        raise GitPullError(f"git 操作失败：{detail[:300]}") from e


def parse_name_status(raw: str) -> ChangedFiles:
    """解析 `git diff --name-status -z` 输出（\\0 分隔，R/C 带两个路径）。"""
    changed = ChangedFiles()
    tokens = [t for t in raw.split("\0")]
    i = 0
    while i < len(tokens):
        status = tokens[i].strip()
        if not status:
            i += 1
            continue
        code = status[0]
        if code in ("R", "C"):  # 改名/复制：旧路径当删除、新路径当新增
            if i + 2 >= len(tokens) or not tokens[i + 1] or not tokens[i + 2]:
                break  # 输出被截断，宁可少算也不能产出空路径
            changed.deleted.append(tokens[i + 1])
            changed.added.append(tokens[i + 2])
            i += 3
            continue
        if i + 1 >= len(tokens):
            break
        path = tokens[i + 1]
        if not path:
            break
        if code == "A":
            changed.added.append(path)
        elif code == "D":
            changed.deleted.append(path)
        elif code in ("M", "T"):  # T = 类型变更（如软链变普通文件），按修改处理
            changed.modified.append(path)
        # U（冲突）/X（未知）忽略：工作副本是 reset --hard 出来的，不该出现
        i += 2
    return changed


def diff_changed_files(repo_dir: Path, old_sha: str, new_sha: str) -> ChangedFiles:
    """两个 commit 之间的变更集。

    浅克隆（depth=1）下旧 commit 仍可达是因为 reset --hard 会留下 reflog；
    一旦被 gc 掉，这里抛 GitDiffError，由管道回退全量重建。
    """
    if not (repo_dir / ".git").exists():
        raise GitDiffError("本地仓库副本不存在或不是 git 仓库")
    if old_sha == new_sha:
        return ChangedFiles()
    try:
        repo = Repo(repo_dir)
        raw = repo.git.diff("--name-status", "-z", f"{old_sha}..{new_sha}")
    except GitCommandError as e:
        raise GitDiffError(f"git diff 不可用：{_sanitize(str(e), None)[:200]}") from e
    except Exception as e:  # noqa: BLE001 — 仓库损坏等一律回退全量
        raise GitDiffError(f"读取仓库失败：{type(e).__name__}") from e
    return parse_name_status(raw)


def head_sha(repo_dir: Path) -> str | None:
    """本地副本当前 HEAD（拉取前调用，作为增量 diff 的基准之一）。"""
    try:
        return Repo(repo_dir).head.commit.hexsha
    except Exception:  # noqa: BLE001 — 无副本/无提交
        return None


def _default_branch(repo: Repo) -> str:
    try:
        ref = repo.git.symbolic_ref("refs/remotes/origin/HEAD", short=True)
        return ref.split("/", 1)[1]
    except GitCommandError:
        return "main"
