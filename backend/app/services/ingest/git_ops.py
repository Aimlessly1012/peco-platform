"""取码与变更集：bundle 主存储、ls-remote 秒回、增量 diff（错误文案不泄露 token）。

M16 起源码的持久层是 MinIO 里的 git bundle，本地只有任务级临时工作区：

    ls_remote_head   一次网络请求拿远端 HEAD——与基准相同就秒回，连 bundle 都不拉
    restore_workdir  拉 bundle → clone → set-url → fetch → 对齐远端（失败逐级回退直接 clone）
    export_bundle    索引成功后 git bundle create --all 推回 MinIO（固定 key 覆盖写）
"""
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from git import Git, GitCommandError, Repo

from app.services.storage import minio_client

logger = logging.getLogger(__name__)

BUNDLE_PREFIX = "repo-bundles/"
BUNDLE_CONTENT_TYPE = "application/x-git-bundle"


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
    if not parsed.hostname:
        # 本地路径/无主机名的 URL 没有可注入凭据的位置。硬拼会拼出
        # "//oauth2:tok@None/path" 这种废 URL，git 报的错还看不出根因
        return git_url
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


def _pull_error(e: Exception, token: str | None) -> GitPullError:
    """GitCommandError → 带中文文案且不含 token 的 GitPullError。"""
    detail = _sanitize(str(e), token)
    if "Authentication failed" in detail or "could not read Username" in detail or "403" in detail:
        return GitPullError("仓库认证失败：请检查 token 是否有效、是否有该仓库读取权限")
    if "not found" in detail.lower() or "404" in detail:
        return GitPullError("仓库不存在或无权访问：请检查 git url")
    if "Could not resolve host" in detail:
        return GitPullError("网络错误：无法解析仓库主机")
    return GitPullError(f"git 操作失败：{detail[:300]}")


def clone_fresh(
    git_url: str, dest: Path, token: str | None = None, branch: str | None = None
) -> str:
    """直接 clone 远端到 dest，返回 HEAD sha。首次索引走它，也是所有 bundle 路径的兜底。

    **不能用 depth=1**：浅克隆做出来的 bundle 是坏的——`git bundle create --all`
    在浅仓库上照样退出 0、照样产出文件，但从那个 bundle clone 时会报
    "remote did not send all necessary objects"。归档看着成功、恢复时才炸，
    是最难查的一种坏法。M16 之前用浅克隆是因为本地副本常驻、不需要完整历史。
    """
    url = _auth_url(git_url, token)
    try:
        _reset_dir(dest)
        kwargs = {"branch": branch} if branch else {}
        repo = Repo.clone_from(url, dest, env={"GIT_TERMINAL_PROMPT": "0"}, **kwargs)
        # 存储的 remote url 还原为无 token 版本，避免密文落盘
        repo.remotes.origin.set_url(git_url)
        return repo.head.commit.hexsha
    except GitCommandError as e:
        raise _pull_error(e, token) from e


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


# ---------------- bundle 主存储（M16 D1/D2/D3/D6） ----------------


def bundle_key(project_id: str) -> str:
    """固定 key 覆盖写（D3）：bundle 自含全部历史，不需要按 commit 攒多份。"""
    return f"{BUNDLE_PREFIX}{project_id}.bundle"


def _reset_dir(path: Path) -> None:
    """清空目录但保留它本身——git clone 要求目标为空，而目录本身是任务工作区。"""
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return
    for child in path.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def _unlink_quiet(path: str | None) -> None:
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def ls_remote_head(
    git_url: str, branch: str | None = None, token: str | None = None
) -> str | None:
    """一次网络请求取远端 HEAD sha（D1）。

    取不到就返回 None（网络抖动、认证失败、分支不存在都算），让任务照常往下走取码
    流程——真正的错误会在那里以带中文文案的 GitPullError 暴露。在这一步提前判死，
    只会把"网络抖了一下"变成"索引失败"。
    """
    url = _auth_url(git_url, token)
    ref = f"refs/heads/{branch}" if branch else "HEAD"
    try:
        git = Git()
        with git.custom_environment(GIT_TERMINAL_PROMPT="0"):
            out = git.ls_remote(url, ref)
    except Exception as e:  # noqa: BLE001 — 见 docstring：这一步不判死
        logger.info(
            "ls-remote 未取到远端 HEAD（%s），按有变更处理",
            _sanitize(str(e), token)[:150],
        )
        return None
    first = (out or "").strip().splitlines()
    if not first:
        return None
    parts = first[0].split()
    return parts[0] if parts else None


def _download_bundle(project_id: str) -> str | None:
    """把 bundle 拉到本地临时文件，返回路径；没有/拉不动一律返回 None。"""
    if not minio_client.storage_enabled():
        return None
    fd, tmp = tempfile.mkstemp(suffix=".bundle", prefix="repo-bundle-")
    os.close(fd)
    try:
        if minio_client.download_file(bundle_key(project_id), tmp):
            return tmp
    except Exception as e:  # noqa: BLE001 — 取不到就退回 clone 远端（D6）
        logger.warning("拉取 bundle 失败（%s），将直接 clone 远端", e)
    _unlink_quiet(tmp)
    return None


def _restore_from_bundle(
    bundle_path: str, git_url: str, dest: Path,
    token: str | None, branch: str | None,
) -> str:
    """bundle → 工作区（D2）。任何一步失败都往外抛，由 restore_workdir 回退。"""
    url = _auth_url(git_url, token)
    kwargs = {"branch": branch} if branch else {}
    # bundle 是本地文件，这一步不碰网络；损坏的 bundle 会在这里报
    # "remote did not send all necessary objects"
    repo = Repo.clone_from(bundle_path, dest, **kwargs)
    target = branch or _current_branch(repo)
    with repo.git.custom_environment(GIT_TERMINAL_PROMPT="0"):
        repo.remotes.origin.set_url(url)          # bundle 文件 → 真实远端
        repo.remotes.origin.fetch(prune=True, tags=True)
        repo.git.checkout(target)
        repo.git.reset("--hard", f"origin/{target}")
    repo.remotes.origin.set_url(git_url)          # 别把 token 留在磁盘上
    return repo.head.commit.hexsha


def restore_workdir(
    project_id: str, git_url: str, dest: Path,
    token: str | None = None, branch: str | None = None,
) -> tuple[str, str]:
    """准备任务工作区，返回 (commit_sha, source)，source ∈ {"bundle", "clone"}。

    D6 容错矩阵：bundle 不存在 / 拉取失败 / 文件损坏 / clone-from-bundle 失败 /
    fetch 失败——任何一环出问题都退回直接 clone 远端。取码这一步只有"远端也拿不到"
    才允许让任务失败。
    """
    bundle = _download_bundle(project_id)
    if bundle is not None:
        try:
            sha = _restore_from_bundle(bundle, git_url, dest, token, branch)
            logger.info("工作区经 bundle 恢复：%s", bundle_key(project_id))
            return sha, "bundle"
        except Exception as e:  # noqa: BLE001 — 逐级 fallback，见 docstring
            logger.warning(
                "bundle 恢复失败（%s），回退直接 clone 远端",
                _sanitize(str(e), token)[:200],
            )
        finally:
            _unlink_quiet(bundle)
    return clone_fresh(git_url, dest, token, branch), "clone"


def export_bundle(project_id: str, repo_dir: Path) -> str | None:
    """git bundle create --all → MinIO 固定 key（D3）。返回 key；存储未启用返回 None。

    失败往外抛，由调用方降级为 warning——与快照归档同一条纪律。
    """
    if not minio_client.storage_enabled():
        return None
    fd, tmp = tempfile.mkstemp(suffix=".bundle", prefix="repo-bundle-")
    os.close(fd)
    try:
        Repo(repo_dir).git.bundle("create", tmp, "--all")
        return minio_client.upload_file(
            bundle_key(project_id), tmp, BUNDLE_CONTENT_TYPE
        )
    finally:
        _unlink_quiet(tmp)


def _current_branch(repo: Repo) -> str:
    try:
        return repo.active_branch.name
    except Exception:  # noqa: BLE001 — 分离头指针等
        return _default_branch(repo)
