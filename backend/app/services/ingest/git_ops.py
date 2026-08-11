"""仓库拉取：clone / fetch+reset，token 认证，错误转可读文案（不泄露 token）。"""
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from git import GitCommandError, Repo


class GitPullError(Exception):
    """携带可读中文错误信息，保证不含 token。"""


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


def _default_branch(repo: Repo) -> str:
    try:
        ref = repo.git.symbolic_ref("refs/remotes/origin/HEAD", short=True)
        return ref.split("/", 1)[1]
    except GitCommandError:
        return "main"
