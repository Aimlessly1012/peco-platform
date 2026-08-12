"""报告生成的 LLM 客户端（复用 summarizer 的客户端/重试模式，设计 D1）。

需求逻辑文档：单次调用；时序图：每模块一次调用 + 校验失败重试 1 次。
任何失败返回 None，由调用方降级，绝不抛到管道。
"""
import asyncio
import logging

from openai import APIError, AsyncOpenAI, RateLimitError

from app.core.config import settings

logger = logging.getLogger(__name__)

CHAPTER_PROMPT = """你是资深软件架构师。为下列功能模块各写一节《需求逻辑文档》正文。

严格格式要求（整篇文档由多批拼接，格式必须统一）：
1. 输出纯 Markdown，不要用 ``` 包裹，不要写文档标题与其他章节
2. 每个模块一节，固定结构：
   ### <模块名>（<类型>{prefix_hint}）
   **业务目标**：一句话
   **核心需求**：2-4 条无序列表
   **关键文件**：列出给定的文件路径
3. 只使用下面给出的信息，不得编造未出现过的模块名、文件路径或接口
4. 中文，每个模块 150 字以内
5. 严格按给定顺序输出全部 {count} 个模块，不要增删

本批模块（共 {count} 个）：
{module_blocks}"""

OVERVIEW_PROMPT = """你是资深软件架构师。基于以下信息写《需求逻辑文档》的开头部分。

严格要求：
1. 输出纯 Markdown，不要用 ``` 包裹
2. 只输出这两节，不要输出功能模块章节（它们由其他部分提供）：
   ## 一、系统概述
   ## 三、端到端业务流
3. 系统概述说明：系统定位、技术栈与架构风格、模块划分逻辑
4. 端到端业务流写 2-4 条主链路，每条串起相关模块名
5. 只使用下面给出的信息，不得编造模块名或接口。中文，600 字以内

项目总览：
{overview}

功能模块地图：
{module_lines}

已生成的模块章节标题：
{chapter_titles}"""

SEQ_PROMPT = """你是资深软件架构师。基于以下功能模块的静态分析数据，画出该模块核心流程的 mermaid 时序图。

严格要求（不满足会被判为无效）：
1. 只输出 mermaid 源码，不要任何解释文字，不要 ``` 围栏
2. 首行必须是 sequenceDiagram
3. 先用 participant 声明全部参与者，别名只用英文字母数字下划线，中文写在 as 之后。
   例：participant FE as 订单页面
4. 消息行只用 `别名A->>别名B: 说明` 或 `别名B-->>别名A: 返回结果` 两种格式，一行一条
5. 除 participant 行与消息行外，不要出现其他任何文字
6. 参与者不少于 3 个（建议：用户、前端、后端接口、服务/数据层），消息 5-12 条
7. 只依据给定数据，不得编造不存在的接口、文件或函数名
{retry_hint}
模块：{name}（类型 {kind}，路由前缀 {prefix}）

模块职责摘要：
{summary}

核心文件职责：
{entry_summaries}

已知前后端调用（前端代码块 → 后端 handler）：
{api_lines}

已知文件依赖（IMPORTS）：
{import_lines}"""


class ReportLLM:
    def __init__(self) -> None:
        self._client: AsyncOpenAI | None = None
        self._semaphore = asyncio.Semaphore(settings.summary_concurrency)

    @property
    def client(self) -> AsyncOpenAI:
        if not settings.chat_api_key:
            raise RuntimeError("未配置 CHAT_API_KEY，无法生成理解报告")
        if self._client is None:
            self._client = AsyncOpenAI(
                base_url=settings.chat_base_url,
                api_key=settings.chat_api_key,
                timeout=settings.llm_timeout_seconds,  # M4 D7
            )
        return self._client

    @property
    def model(self) -> str:
        return settings.chat_model

    async def _complete(self, prompt: str, max_tokens: int) -> str | None:
        delay = 2.0
        for attempt in range(3):
            try:
                async with self._semaphore:
                    resp = await self.client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2,
                        max_tokens=max_tokens,
                    )
                text = (resp.choices[0].message.content or "").strip()
                if text:
                    return text
            except (RateLimitError, APIError, TimeoutError) as e:
                logger.warning("报告 LLM 调用失败（%s），%.0fs 后重试", type(e).__name__, delay)
                if attempt < 2:
                    await asyncio.sleep(delay)
                    delay *= 2
            except Exception as e:  # noqa: BLE001 — 报告失败必须降级而非中断索引
                logger.warning("报告 LLM 调用异常（%s: %s），放弃", type(e).__name__, e)
                return None
        return None

    async def generate_chapters(self, module_blocks: str, count: int) -> str | None:
        """一批模块的章节正文（M5 D3 的 map 步）。"""
        prompt = CHAPTER_PROMPT.format(
            count=count,
            prefix_hint="，路由 <前缀>",
            module_blocks=module_blocks[:8000],
        )
        return await self._complete(prompt, max_tokens=2500)

    async def generate_overview(
        self, overview: str, module_lines: str, chapter_titles: str
    ) -> str | None:
        """系统概述 + 端到端业务流（M5 D3 的 reduce 步，单次小调用）。"""
        prompt = OVERVIEW_PROMPT.format(
            overview=overview[:2000] or "（无项目总览）",
            module_lines=module_lines[:3000] or "（无模块）",
            chapter_titles=chapter_titles[:2000] or "（无章节）",
        )
        return await self._complete(prompt, max_tokens=1200)

    async def generate_sequence(
        self,
        name: str,
        kind: str,
        prefix: str,
        summary: str,
        entry_summaries: str,
        api_lines: str,
        import_lines: str,
        retry_reason: str = "",
    ) -> str | None:
        retry_hint = (
            f"\n上一次生成被判为无效，原因：{retry_reason}。请严格按上述格式重新输出。\n"
            if retry_reason
            else "\n"
        )
        prompt = SEQ_PROMPT.format(
            retry_hint=retry_hint,
            name=name, kind=kind, prefix=prefix or "（无）",
            summary=summary[:1200] or "（无摘要）",
            entry_summaries=entry_summaries[:2000] or "（无）",
            api_lines=api_lines[:2000] or "（无已知前后端调用）",
            import_lines=import_lines[:1500] or "（无已知依赖）",
        )
        return await self._complete(prompt, max_tokens=1200)


report_llm = ReportLLM()
