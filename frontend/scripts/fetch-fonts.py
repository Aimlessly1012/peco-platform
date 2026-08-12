#!/usr/bin/env python3
"""把 Google Fonts 的字体抓成自托管资源（运行时不再依赖 CDN）。

用法（在 frontend/ 下执行）：
    python3 scripts/fetch-fonts.py

做三件事：
1. 以浏览器 UA 请求 Google Fonts CSS2（UA 决定返回 woff2 还是 ttf）；
2. 把其中每个 @font-face 的字体文件下载到 public/fonts/，文件名语义化；
3. 生成 app/fonts.css —— 与线上 CSS 等价，只是 src 指向本地，unicode-range 原样保留。

只有需要换字体/换字重/升级字体版本时才需要重跑；日常构建不依赖本脚本。
字体许可：IBM Plex Mono 与 Noto Sans SC 均为 SIL Open Font License 1.1，允许自托管与再分发。
"""

from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

# 与 tailwind.config.ts 的 fontFamily.mono 保持一致
CSS_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=IBM+Plex+Mono:wght@400;500;600"
    "&family=Noto+Sans+SC:wght@400;500;700"
    "&display=swap"
)
# 不带浏览器 UA 会拿到 ttf 版本，体积大好几倍
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "public" / "fonts"
CSS_OUT = ROOT / "app" / "fonts.css"

FACE = re.compile(r"@font-face\s*\{(?P<body>.*?)\}", re.S)
# 紧贴在 @font-face 之前的子集注释（中间只允许空白）
TRAILING_COMMENT = re.compile(r"/\*\s*([^*]+?)\s*\*/\s*$")


def fetch(url: str) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": UA}), timeout=60) as r:
        return r.read()


def field(body: str, name: str) -> str:
    m = re.search(rf"{name}:\s*([^;]+);", body)
    return m.group(1).strip() if m else ""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.strip().strip("'\"").lower()).strip("-")


def parse(css: str) -> list[dict]:
    rows: list[dict] = []
    for m in FACE.finditer(css):
        body = m.group("body")
        src = re.search(r"url\((https://[^)]+\.woff2)\)", body)
        if not src:
            continue
        url = src.group(1)
        family = field(body, "font-family").strip("'\"")
        weight = field(body, "font-weight")

        comment = TRAILING_COMMENT.search(css[: m.start()])
        if comment:
            subset = slug(comment.group(1))
        else:
            # Google 没给中文分片加注释，只能用 URL 里的分片序号
            part = re.search(r"\.(\d+)\.woff2$", url)
            subset = f"cjk-{part.group(1)}" if part else slug(url[-24:])

        rows.append(
            {
                "family": family,
                "weight": weight,
                "style": field(body, "font-style"),
                "display": field(body, "font-display") or "swap",
                "urange": field(body, "unicode-range"),
                "url": url,
                "file": f"{slug(family)}-{weight}-{subset}.woff2",
            }
        )
    return rows


def render_css(rows: list[dict]) -> str:
    out = [
        "/* 本地字体：原先从 Google Fonts CDN 引入，现自托管于 public/fonts/。",
        " * 本文件由 scripts/fetch-fonts.py 生成，请勿手改。",
        " * 保留了原始 unicode-range 分片，浏览器只下载页面实际命中的分片。",
        " */",
        "",
    ]
    for r in rows:
        out += [
            "@font-face {",
            f"  font-family: '{r['family']}';",
            f"  font-style: {r['style']};",
            f"  font-weight: {r['weight']};",
            f"  font-display: {r['display']};",
            f"  src: url('/fonts/{r['file']}') format('woff2');",
        ]
        if r["urange"]:
            out.append(f"  unicode-range: {r['urange']};")
        out.append("}")
    return "\n".join(out) + "\n"


def main() -> int:
    print(f"拉取 CSS: {CSS_URL}")
    rows = parse(fetch(CSS_URL).decode("utf-8"))
    if not rows:
        print("没解析到任何 woff2 @font-face，检查 UA 或 URL", file=sys.stderr)
        return 1

    names = [r["file"] for r in rows]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        print(f"文件名冲突: {sorted(dupes)[:5]}", file=sys.stderr)
        return 1

    FONT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in FONT_DIR.glob("*.woff2"):
        if stale.name not in set(names):
            stale.unlink()
            print(f"删除旧字体 {stale.name}")

    def grab(row: dict) -> int:
        target = FONT_DIR / row["file"]
        data = fetch(row["url"])
        if not data.startswith(b"wOF2"):
            raise RuntimeError(f"{row['file']} 不是合法 woff2")
        target.write_bytes(data)
        return len(data)

    with ThreadPoolExecutor(max_workers=10) as pool:
        total = sum(pool.map(grab, rows))

    CSS_OUT.write_text(render_css(rows), encoding="utf-8")

    families: dict[str, int] = {}
    for r in rows:
        families[r["family"]] = families.get(r["family"], 0) + 1
    print(f"\n下载 {len(rows)} 个 woff2，共 {total / 1024 / 1024:.1f} MB → {FONT_DIR}")
    for fam, n in sorted(families.items()):
        print(f"  {fam}: {n} 个分片")
    print(f"样式表 → {CSS_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
