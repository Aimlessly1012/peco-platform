"""报告生成的 LLM 客户端（复用 summarizer 的客户端/重试模式，设计 D1）。

需求逻辑文档：分批调用；时序图与功能点：每模块一次调用 + 失败重试。
任何失败返回 None，由调用方降级，绝不抛到管道。

max_tokens 说明：对推理型模型（如 deepseek-v4-flash）这是"推理 + 正文"的总预算，
给紧了会拿到 finish_reason=length 且 content 为空。各处预算已按实测的推理开销放宽，
按实际用量计费，放宽不增加成本。
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

GROUP_PROMPT = """你是资深产品经理。下面是一个软件产品的全部功能域清单，\
请把它们按**业务归属**分组，用于画产品功能思维导图的中间层级。

严格要求（不满足会被判为无效）：
1. 只输出 JSON，不要解释、不要代码围栏，格式：{{"业务组名": ["功能域名", ...], ...}}
2. 组名用中文业务词（如「任务中心」「活动奖励」「内容分享」「账号与权限」），\
禁止技术词（模块、服务、组件、接口、页面、后台、前端）
3. 分成 {min_groups}-{max_groups} 组；命名相近的功能域要归到同一组\
（例如 taskCenter、taskCenterDetail、taskList 都属于「任务中心」）
4. 每个功能域必须且只能出现一次，名称必须与清单里的**完全一致**，不要改写或翻译
5. 不要遗漏任何功能域；实在归不了类的放进「其他」组

功能域清单（共 {count} 个）：
{domain_lines}"""


FEATURE_PROMPT = """你是资深产品经理。下面是某个软件模块的静态分析结果，请提炼这个模块\
**对用户提供了哪些功能**，用于画产品功能思维导图。

严格要求（不满足会被判为无效）：
1. 只输出功能点，每行一条，以「- 」开头，不要标题、不要解释、不要空行
2. 输出 2-6 条，每条不超过 14 个字
3. 每条必须是中文动宾短语（动词开头），例如「创建广告任务」「导出结算报表」
4. 禁止出现技术词：组件、接口、文件、模块、函数、类、路由、API、CRUD、封装、渲染
5. 只能依据下面给出的信息提炼，禁止编造清单中不存在的能力
6. 入口清单里的技术辅助项（类型定义、请求封装、工具函数、卡片/弹窗等 UI 零件）\
不要单独成条，把它们服务的那个业务功能写出来即可
7. 至少输出 1 条。信息少就少写几条，宁少勿编；但不要输出空内容

模块名称：{name}
模块类型：{kind_label}
{prefix_line}
模块职责摘要：
{summary}

该模块的实际入口清单（文件路径与其中的函数名）：
{anchors}"""

FLOW_PROMPT = """你是资深产品经理。下面是某系统的业务分析结果，请把其中的**核心业务流程**\
画成流程图，给业务人员看。

严格要求（不满足会被判为无效）：
1. 为每条核心业务流输出一节，最多 {max_flows} 条，格式严格如下（标题行 + 围栏代码块）：
## <业务流名称，≤12 字>
```mermaid
flowchart TD
    A[用户提交订单] --> B{{是否有库存}}
    B -->|有| C[生成订单]
    B -->|无| D[提示缺货]
```
2. 每张图不超过 {max_nodes} 个节点，节点文案不超过 12 个字
3. 节点写**业务步骤**：用户动作或系统行为，例如「填写投放信息」「系统校验预算」「生成结算单」
4. 严禁出现文件名、函数名、表名与技术词（组件、接口、函数、模块、路由、API、数据库）
5. 判断分支用 {{}} 节点并在连线上标注条件，例如 B -->|审核通过| C
6. 只依据下面给出的信息画，禁止编造未提及的环节；信息不足就少画几条
7. 除标题行与代码块外不要输出任何其他文字

系统的核心业务流（来自项目总览）：
{flow_lines}

相关功能域的关键流程：
{module_flows}"""

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
                # 空内容多半是 max_tokens 被推理过程吃光——静默重试会让人以为没调用过
                logger.warning(
                    "报告 LLM 返回空内容（第 %d 次，max_tokens=%d）", attempt + 1, max_tokens
                )
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
        return await self._complete(prompt, max_tokens=5000)

    async def generate_overview(
        self, overview: str, module_lines: str, chapter_titles: str
    ) -> str | None:
        """系统概述 + 端到端业务流（M5 D3 的 reduce 步，单次小调用）。"""
        prompt = OVERVIEW_PROMPT.format(
            overview=overview[:2000] or "（无项目总览）",
            module_lines=module_lines[:3000] or "（无模块）",
            chapter_titles=chapter_titles[:2000] or "（无章节）",
        )
        return await self._complete(prompt, max_tokens=2500)

    async def group_domains(
        self, domain_lines: str, count: int, min_groups: int = 3, max_groups: int = 10
    ) -> str | None:
        """功能域业务归组（M6 B6）：单次调用，输出 JSON。"""
        prompt = GROUP_PROMPT.format(
            count=count, domain_lines=domain_lines[:6000],
            min_groups=min_groups, max_groups=max_groups,
        )
        # 推理开销随域数增长且波动大：55 域实测 4000 全被 reasoning 吃光（content 空），
        # 12250 也偶发三连空。按域数线性放宽，计费按实际用量，给宽不增加成本
        return await self._complete(prompt, max_tokens=min(6000 + 200 * count, 16000))

    async def generate_features(
        self, name: str, kind_label: str, route_prefix: str, summary: str, anchors: str
    ) -> str | None:
        """单模块功能点提取（M6 D1）：输入小、可缓存、失败只影响该功能域。"""
        prompt = FEATURE_PROMPT.format(
            name=name,
            kind_label=kind_label,
            prefix_line=f"访问路径前缀：{route_prefix}" if route_prefix else "",
            summary=summary[:800] or "（无摘要）",
            anchors=anchors[:1500] or "（无入口清单）",
        )
        # 输出本身只有几十 token，但 max_tokens 是"推理 + 正文"的总预算。
        # 信息越模糊模型纠结越久（实测 800 全被 reasoning 吃光、content 为空），
        # 预算按实际用量计费，给宽不增加成本
        return await self._complete(prompt, max_tokens=2000)

    async def generate_business_flows(
        self, flow_lines: str, module_flows: str,
        max_flows: int = 4, max_nodes: int = 8, retry_reason: str = "",
    ) -> str | None:
        """业务流程图（M6 B5）：单次调用产出 2-4 张 flowchart。"""
        prompt = FLOW_PROMPT.format(
            max_flows=max_flows, max_nodes=max_nodes,
            flow_lines=flow_lines[:1500] or "（无）",
            module_flows=module_flows[:4000] or "（无）",
        )
        if retry_reason:
            prompt += f"\n\n上一次输出被判为无效，原因：{retry_reason}。请严格按格式重新输出。"
        # 多张图 + 推理预算（见模块 docstring）
        return await self._complete(prompt, max_tokens=6000)

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
        # 时序图正文本身就要 300-500 token，1200 的总预算会被推理吃光后交出空内容，
        # 校验必然失败并降级——M5 现场"时序图 3/6 降级"的真实根因
        return await self._complete(prompt, max_tokens=3000)


report_llm = ReportLLM()
