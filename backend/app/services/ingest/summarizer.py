"""四层摘要生成（设计 D4）：L2 文件 / L3 模块 / L4 项目，flash 档模型 + 分层缓存 + 降级。"""
import asyncio
import hashlib
import logging

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
        prompt = L2_PROMPT.format(
            path=path,
            imports=", ".join(sorted(imports)) or "无仓库内依赖",
            head=head[:600],
            symbols=symbols[:1500],
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
