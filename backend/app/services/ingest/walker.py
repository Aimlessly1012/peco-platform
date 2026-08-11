"""文件遍历与过滤：.gitignore + 内置忽略表 + 大小/二进制/扩展名过滤。"""
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

from app.core.config import settings

# 语言路由：扩展名 → tree-sitter 语言名
LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}

# 内置忽略目录（即使不在 .gitignore 中也跳过）
BUILTIN_IGNORE_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "__pycache__",
    "venv", ".venv", ".turbo", "coverage", ".pytest_cache", ".idea",
    ".vscode", "out", "target", "vendor", ".cache", "egg-info",
}


@dataclass
class WalkResult:
    files: list[Path] = field(default_factory=list)  # 相对路径
    skipped: int = 0


def _load_gitignore(repo_dir: Path) -> pathspec.PathSpec | None:
    gitignore = repo_dir / ".gitignore"
    if not gitignore.exists():
        return None
    try:
        lines = gitignore.read_text(encoding="utf-8", errors="ignore").splitlines()
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)
    except OSError:
        return None


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(4096)
    except OSError:
        return True


def walk_repo(repo_dir: Path) -> WalkResult:
    """遍历仓库，返回可解析文件的相对路径清单与跳过计数。"""
    spec = _load_gitignore(repo_dir)
    result = WalkResult()

    for path in sorted(repo_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_dir)
        parts = set(rel.parts[:-1])
        if parts & BUILTIN_IGNORE_DIRS or any(p.endswith(".egg-info") for p in rel.parts):
            continue  # 内置忽略目录不计入 skipped（噪音太大）
        if spec and spec.match_file(str(rel)):
            continue
        if rel.suffix.lower() not in LANGUAGE_BY_EXT:
            result.skipped += 1
            continue
        try:
            if path.stat().st_size > settings.max_file_bytes:
                result.skipped += 1
                continue
        except OSError:
            result.skipped += 1
            continue
        if _is_binary(path):
            result.skipped += 1
            continue
        result.files.append(rel)

    return result
