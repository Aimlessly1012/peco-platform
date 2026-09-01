"""四层摘要生成（设计 D4）：L2 文件 / L3 模块 / L4 项目，flash 档模型 + 分层缓存 + 降级。

M5：L2 先经规则分级判定（rule_summary）免 LLM，未命中者按文件规模分档给输入。
"""
import asyncio
import hashlib
import logging
import re

from openai import APIError, AsyncOpenAI, RateLimitError

from app.core.config import settings
from app.services.ingest.chunker import CodeChunk
from app.services.ingest.router_parser import ModuleMap

logger = logging.getLogger(__name__)

L2_PROMPT = """根据以下信息，用一段话（不超过 80 字）概括这个代码文件的职责。只输出概括文字本身。

文件路径：{path}
导入依赖：{imports}
头部内容：
{head}
定义的符号：
{symbols}"""

L3_PROMPT = """根据功能模块内各文件的职责摘要与路由入口，输出该模块的摘要，格式：
业务目标：<一句话>
关键流程：<2-4 条，每条一行，描述数据/请求怎么流转>
核心文件：<逗号分隔的文件路径>
不超过 200 字。

模块名：{name}（类型 {kind}，路由前缀 {prefix}）
路由入口：
{entries}
文件职责：
{file_summaries}"""

L4_PROMPT = """根据以下信息生成项目总览，格式：
项目定位：<一两句>
技术栈：<一句>
架构风格：<一句>
核心业务流：<2-4 条>
不超过 300 字。

README 摘录：
{readme}
功能模块地图：
{module_lines}
各模块摘要：
{module_summaries}"""


# ---------------- 规则分级摘要（M5 D5） ----------------

# 按完整路径段匹配，不能用子串——"src/contest/" 含 "test/"，会把业务文件误判成测试
TEST_DIR_SEGMENTS = {"test", "tests", "__tests__", "spec", "specs", "__mocks__", "e2e"}
TEST_NAME_MARKERS = (".test.", ".spec.", "_test.", ".e2e.")
TYPE_SYMBOL_TYPES = {"interface", "type", "enum", "type_alias"}
CONFIG_NAME_MARKERS = ("config", "constants", "constant", "settings", "env")
SMALL_FILE_LINES = 30
RULE_SYMBOL_LIMIT = 12

# fast 模式产物的标记前缀：这类摘要是"待升级"的占位，不得进摘要缓存
FAST_PREFIX = "（快速模式）"
FAILED_PREFIX = "（摘要生成失败"


def _real_symbols(chunks: list[CodeChunk]) -> list[CodeChunk]:
    """排除 module 级聚合块（import 语句那一坨），只留真实定义。"""
    return [c for c in chunks if c.symbol and c.symbol != "(module)"]


def _symbol_names(chunks: list[CodeChunk], limit: int = RULE_SYMBOL_LIMIT) -> str:
    names = [c.symbol for c in chunks[:limit]]
    suffix = f" 等 {len(chunks)} 个" if len(chunks) > limit else ""
    return (", ".join(names) or "无") + suffix


def _file_line_count(chunks: list[CodeChunk]) -> int:
    return max((c.end_line for c in chunks), default=0)


def _is_test_file(path: str) -> bool:
    lowered = path.lower()
    segments = lowered.split("/")
    name = segments[-1]
    return (
        bool(set(segments[:-1]) & TEST_DIR_SEGMENTS)
        or any(marker in name for marker in TEST_NAME_MARKERS)
        or name.startswith("test_")
    )


def _is_type_only(path: str, symbols: list[CodeChunk]) -> bool:
    if path.endswith(".d.ts"):
        return True
    # 保守：必须有符号且全部是类型声明，一个函数都不能有
    return bool(symbols) and all(c.symbol_type in TYPE_SYMBOL_TYPES for c in symbols)


def _is_barrel(path: str, chunks: list[CodeChunk], symbols: list[CodeChunk]) -> bool:
    """纯导出 barrel：module 块外没有任何定义，且 module 块里确实有 export。"""
    if symbols or not chunks:
        return False
    module_code = "\n".join(c.code for c in chunks if c.symbol == "(module)")
    return "export" in module_code or "from" in module_code


def _is_config(path: str, symbols: list[CodeChunk]) -> bool:
    name = path.lower().rsplit("/", 1)[-1]
    if any(marker in name for marker in CONFIG_NAME_MARKERS):
        return bool(symbols)
    # 或者符号全是大写常量（保守：至少 2 个，避免单个常量文件误判）
    return len(symbols) >= 2 and all(
        c.symbol.isupper() or c.symbol.replace("_", "").isupper() for c in symbols
    )


def _barrel_sources(chunks: list[CodeChunk], limit: int = 8) -> str:
    """从 module 块里抠出 from '...' 的来源清单。"""
    sources: list[str] = []
    for chunk in chunks:
        for match in re.finditer(r"from\s+['\"]([^'\"]+)['\"]", chunk.code):
            source = match.group(1)
            if source not in sources:
                sources.append(source)
    shown = sources[:limit]
    suffix = f" 等 {len(sources)} 个来源" if len(sources) > limit else ""
    return (", ".join(shown) or "同目录模块") + suffix


def _signature_line(chunk: CodeChunk) -> str:
    return f"{chunk.symbol_type} {chunk.symbol}"


def rule_summary(path: str, chunks: list[CodeChunk]) -> str | None:
    """规则摘要（M5 D5）：命中返回确定性摘要文本，未命中返回 None 交给 LLM。

    判定按序进行且条件保守（要求全符号匹配），宁可漏判走 LLM，也不能把业务文件
    误判成样板文件——检索主力是代码嵌入，摘要略糙可接受，摘错则会误导。
    """
    symbols = _real_symbols(chunks)

    if _is_test_file(path):
        return f"{path} 的测试用例，覆盖：{_symbol_names(symbols)}"
    if _is_type_only(path, symbols):
        return f"类型定义：{_symbol_names(symbols)}"
    if _is_barrel(path, chunks, symbols):
        return f"聚合导出：{_barrel_sources(chunks)}"
    if _is_config(path, symbols):
        return f"配置常量：{_symbol_names(symbols)}"
    if chunks and _file_line_count(chunks) < SMALL_FILE_LINES:
        signatures = "；".join(_signature_line(c) for c in symbols[:RULE_SYMBOL_LIMIT])
        return f"小文件（{_file_line_count(chunks)} 行）：{signatures or '仅模块级语句'}"
    return None


def fast_summary(path: str, chunks: list[CodeChunk]) -> str:
    """fast 模式下未命中规则的文件（零 LLM）。

    前缀 FAST_PREFIX 让这类摘要不进摘要缓存（见 load_summary_cache 的过滤）——
    否则 fast→deep 补跑时会命中缓存，永远拿不到真正的 LLM 摘要。
    """
    symbols = ", ".join(c.symbol for c in _real_symbols(chunks))[:200]
    return f"{FAST_PREFIX}{path}：{symbols or '无顶层符号'}"


def template_module_summary(name: str, kind: str, prefix: str, files: list[str]) -> str:
    """fast 模式的 L3 模板（零 LLM）。同样带 FAST_PREFIX，不进 L3 缓存。"""
    shown = files[:10]
    suffix = f" 等 {len(files)} 个文件" if len(files) > 10 else ""
    return (
        f"{FAST_PREFIX}{name} 模块（{kind}{'，路由 ' + prefix if prefix else ''}），"
        f"含 {len(files)} 个文件：{', '.join(shown)}{suffix}"
    )


def template_project_summary(module_map: ModuleMap) -> str:
    """fast 模式的 L4 模板（零 LLM）：路由地图直出。"""
    lines = [
        f"- [{m.kind}] {m.name}"
        f"{'（路由 ' + m.route_prefix + '）' if m.route_prefix else ''}"
        for m in module_map.modules[:40]
    ]
    more = (
        f"\n- … 另有 {len(module_map.modules) - 40} 个模块"
        if len(module_map.modules) > 40
        else ""
    )
    return (
        f"（快速模式概览）本项目共 {len(module_map.modules)} 个功能模块：\n"
        + "\n".join(lines)
        + more
    )


def fallback_summary(path: str, chunks: list[CodeChunk]) -> str:
    """摘要失败降级：符号清单占位（spec: 摘要失败降级）。"""
    symbols = ", ".join(c.symbol for c in chunks if c.symbol != "(module)")[:200]
    return f"（摘要生成失败，符号清单）{path}: {symbols or '无符号'}"


def module_agg_hash(file_hashes: list[str]) -> str:
    """L3 缓存键：模块内文件 hash 集合的聚合。"""
    joined = "|".join(sorted(file_hashes))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


class Summarizer:
    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        self._semaphore = asyncio.Semaphore(settings.summary_concurrency)

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            if not settings.chat_api_key:
                raise RuntimeError("未配置 CHAT_API_KEY，无法调用摘要服务")
            self._client = AsyncOpenAI(
                base_url=settings.chat_base_url,
                api_key=settings.chat_api_key,
                timeout=settings.llm_timeout_seconds,  # M4 D7：超时进入既有退避降级
            )
        return self._client

    @property
    def model(self) -> str:
        return settings.summary_model or settings.chat_model

    async def _complete(self, prompt: str) -> str | None:
        delay = 2.0
        for attempt in range(3):
            try:
                async with self._semaphore:
                    resp = await self.client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                        max_tokens=500,
                    )
                text = (resp.choices[0].message.content or "").strip()
                if text:
                    return text
            except (RateLimitError, APIError, TimeoutError) as e:
                logger.warning("摘要调用失败（%s），%.0fs 后重试", type(e).__name__, delay)
                if attempt < 2:
                    await asyncio.sleep(delay)
                    delay *= 2
        return None

    async def summarize_file(
        self, path: str, imports: set[str], chunks: list[CodeChunk], head: str
    ) -> str | None:
        symbols = "\n".join(
            f"- {c.symbol_type} {c.symbol} (L{c.start_line}-{c.end_line})"
            for c in chunks
            if c.symbol != "(module)"
        ) or "（无顶层符号）"
        # M5 D6：按文件规模分档给输入——小文件给满额头部纯属浪费 token
        lines = _file_line_count(chunks)
        if lines < 100:
            head_budget, symbol_budget = 0, 800
        elif lines <= 400:
            head_budget, symbol_budget = 300, 800
        else:
            head_budget, symbol_budget = 600, 1500
        prompt = L2_PROMPT.format(
            path=path,
            imports=", ".join(sorted(imports)) or "无仓库内依赖",
            head=head[:head_budget] if head_budget else "（小文件，见符号清单）",
            symbols=symbols[:symbol_budget],
        )
        return await self._complete(prompt)

    async def summarize_module(
        self, name: str, kind: str, prefix: str,
        entries: list[str], file_summaries: dict[str, str],
    ) -> str | None:
        lines = "\n".join(f"- {p}: {s}" for p, s in list(file_summaries.items())[:30])
        prompt = L3_PROMPT.format(
            name=name, kind=kind, prefix=prefix or "（无）",
            entries="\n".join(f"- {e}" for e in entries[:15]) or "（无）",
            file_summaries=lines or "（无）",
        )
        return await self._complete(prompt)

    async def summarize_project(
        self, readme: str, module_map: ModuleMap, module_summaries: dict[str, str]
    ) -> str | None:
        module_lines = "\n".join(
            f"- [{m.kind}] {m.name} ({m.route_prefix or '-'})，入口 {len(m.entry_files)} 个文件"
            for m in module_map.modules
        )
        summaries = "\n".join(
            f"## {name}\n{text}" for name, text in module_summaries.items()
        )
        prompt = L4_PROMPT.format(
            readme=readme[:1500] or "（无 README）",
            module_lines=module_lines,
            module_summaries=summaries[:4000],
        )
        return await self._complete(prompt)


summarizer = Summarizer()
