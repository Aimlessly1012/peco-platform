"""LangGraph 问答工作流（M9 起三节点）：understand → retrieve → generate。

- understand：一次调用同时完成"改写追问"与"分类 global|local|impact"（M9 D3），
  解析失败退回原问题 + local（与合并前各自的降级语义一致）
- generate 的 LLM 调用带 tags=["answer"]，SSE 层只转发该标签的 token 流，
  避免 understand 的输出混入答案。
"""
import json
import logging
import re
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.services.retrieval.service import (
    MAX_IMPACT_DEPTH,
    RetrievedItem,
    format_impact_context,
    get_project_summary,
    impact_of,
    search_layered,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是代码仓库问答助手。基于给出的项目资料回答用户关于该项目的问题。

资料分三类：
- 【项目总览】【模块摘要】【文件职责】：索引时生成的理解层摘要，适合回答架构/流程类问题
- 【代码片段】：直接命中的源码
- 标注「关联带出」的条目：与命中代码相连的上下文（同文件/被调用接口/依赖）

规则：
1. 只依据提供的资料回答，不要编造不存在的代码或文件
2. 用到某条资料时，在该句句末标注它的编号，格式 [n]——n 取自资料标题「### 资料 N:」中的 N。
   一句同时依据多条资料就连写 [2][5]。只标真正用到的资料，不要罗列全部编号；
   编号必须是资料里出现过的，没用到资料的句子不加标注。
   开头的【项目总览】是背景信息、没有编号，不要为它编造编号
3. 提到具体代码时同时给出出处，格式：`文件路径:起始行`；引用摘要时标注模块或文件名
4. 资料不足以回答时如实说明，并给出已看到的相关线索
5. 给出【影响面分析】资料时，按「直接引用 / 间接影响（注明跳数）/ 波及的前端与模块」分层回答，
   每层列出具体文件路径；没有引用者时明确说明"未发现其他文件引用它"
6. 用中文回答，代码保持原文"""

UNDERSTAND_PROMPT = """你要为一个代码仓库问答系统做两件事：改写问题、判断问题类型。

严格只输出一个 JSON 对象，不要解释、不要代码围栏：
{{"rewritten": "改写后的完整问题", "type": "global|local|impact"}}

改写规则：结合对话历史，把最新问题补全成不依赖上下文、可独立理解的问题；
本来就完整的问题原样返回。无对话历史时直接返回原问题。

类型规则：
- global：项目整体——架构、技术栈、入口、整体流程、模块划分、"这个项目是干嘛的"
- local：具体代码——某函数/类/文件在哪、怎么实现、某段逻辑、某接口细节
- impact：改动波及——改/删/重构某文件或函数会影响什么、谁依赖它、要回归测哪些地方

例子：
问题"这个项目的整体架构是什么" → {{"rewritten": "这个项目的整体架构是什么", "type": "global"}}
问题"create_order 函数在哪" → {{"rewritten": "create_order 函数在哪", "type": "local"}}
问题"改 order_service.py 会影响哪些地方" → {{"rewritten": "改 order_service.py 会影响哪些地方", "type": "impact"}}
历史提到订单模块、问题"那它的取消逻辑呢" → {{"rewritten": "订单模块的取消逻辑是怎么实现的", "type": "local"}}

对话历史：
{history}

最新问题：{question}"""

class QAState(TypedDict, total=False):
    project_id: str
    question: str
    history: list[dict]
    rewritten_question: str
    question_type: str
    items: list[RetrievedItem]
    context_text: str
    project_summary: str


def build_llm(streaming: bool = True) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.chat_base_url,
        api_key=settings.chat_api_key,
        model=settings.chat_model,
        streaming=streaming,
        temperature=0.1,
    )


def parse_understanding(raw: str, question: str) -> tuple[str, str]:
    """解析合并调用的 JSON 输出 → (改写后问题, 类型)。

    任何解析问题都退回 (原问题, local)——与合并前 rewrite/classify 各自的降级语义一致。
    """
    text = (raw or "").strip()
    if not text:
        return question, "local"
    match = re.search(r"\{.*\}", text, re.S)
    if match is None:
        return question, "local"
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return question, "local"
    if not isinstance(data, dict):
        return question, "local"

    rewritten = data.get("rewritten")
    rewritten = rewritten.strip() if isinstance(rewritten, str) else ""

    qtype = str(data.get("type", "")).strip().lower()
    # impact 先判：影响面问题的描述里常常也带 global/local 字样
    if "impact" in qtype:
        question_type = "impact"
    elif "global" in qtype:
        question_type = "global"
    else:
        question_type = "local"
    return rewritten or question, question_type


async def understand_node(state: QAState) -> QAState:
    """改写 + 分类合并成一次 LLM 调用（M9 D3）。

    合并前是两次串行调用，各 3-10s，首答前白等一轮。两件事输入相同、输出都很短，
    没有拆开的必要。失败时退回 (原问题, local)——与原先两个节点各自的降级一致。
    """
    question = state["question"]
    history_text = "\n".join(
        f"{m['role']}: {m['content'][:300]}" for m in state.get("history", [])[-6:]
    ) or "（无）"
    try:
        llm = build_llm(streaming=False)
        resp = await llm.ainvoke(
            [HumanMessage(content=UNDERSTAND_PROMPT.format(
                history=history_text, question=question
            ))],
            config={"tags": ["internal"]},
        )
        rewritten, question_type = parse_understanding(resp.content or "", question)
    except Exception:  # noqa: BLE001 — 理解失败不该让问答中断
        logger.warning("问题理解调用失败，退回原问题 + local", exc_info=True)
        rewritten, question_type = question, "local"
    return {"rewritten_question": rewritten, "question_type": question_type}


def _format_item(i: int, item: RetrievedItem) -> str:
    via = "（关联带出）" if item.via_edge else ""
    if item.kind == "module_summary":
        return f"### 资料 {i}: 【模块摘要】{item.symbol} {via}\n{item.content}"
    if item.kind == "file_summary":
        return f"### 资料 {i}: 【文件职责】{item.file_path} {via}\n{item.content}"
    lang = item.file_path.rsplit(".", 1)[-1] if "." in item.file_path else ""
    return (
        f"### 资料 {i}: 【代码片段】{item.file_path}:{item.start_line}-{item.end_line} "
        f"({item.symbol_type} {item.symbol}) {via}\n```{lang}\n{item.content}\n```"
    )


async def _impact_context(project_id: str, question: str, items: list[RetrievedItem]) -> str:
    """影响面资料块（M4 D5）：向量命中的最优块所在文件为起点，做多跳反查。

    定位不到目标文件时返回空串——调用方据此退化为普通 local 回答（spec: 降级不报错）。
    """
    target = next((i.file_path for i in items if i.kind == "chunk" and i.file_path), "")
    if not target:
        target = next((i.file_path for i in items if i.file_path), "")
    if not target:
        logger.info("影响面问题未定位到目标文件，降级为 local 检索")
        return ""
    try:
        impact = await impact_of(project_id, target, max_depth=MAX_IMPACT_DEPTH)
    except Exception:  # noqa: BLE001 — 影响面失败不该让问答挂掉
        logger.warning("影响面查询失败，降级为 local 检索", exc_info=True)
        return ""
    return format_impact_context(impact)


async def retrieve_node(state: QAState) -> QAState:
    question = state.get("rewritten_question") or state["question"]
    qtype = state.get("question_type", "local")
    # impact 的目标定位与常规回答都需要局部检索结果，故检索策略同 local；
    # 但要把 impact 透传下去——检索层据此跳过 rerank（M7 D2：它按图距离排序）
    items = await search_layered(state["project_id"], question, qtype)

    parts = [_format_item(i + 1, item) for i, item in enumerate(items)]
    project_summary = ""
    if qtype == "global":
        project_summary = await get_project_summary(state["project_id"])
        if project_summary:
            # 不给编号：它不在 items 里，没有对应的 citation 条目，标题里写明避免模型误编号
            parts.insert(0, f"### 【项目总览】（背景信息，无编号，不要标注）\n{project_summary}")
    if qtype == "impact":
        impact_text = await _impact_context(state["project_id"], question, items)
        if impact_text:
            # 同样不编号：影响树不是 items 里的条目，编号会挤掉 citations 的对应关系
            parts.insert(0, f"### 【影响面分析】（背景信息，无编号，不要标注）\n{impact_text}")
    return {
        "items": items,
        "context_text": "\n\n".join(parts),
        "project_summary": project_summary,
    }


async def generate_node(state: QAState) -> QAState:
    llm = build_llm()
    history_text = ""
    if state.get("history"):
        rounds = [f"{m['role']}: {m['content'][:500]}" for m in state["history"][-6:]]
        history_text = "\n\n## 对话历史（供理解指代）\n" + "\n".join(rounds)

    prompt = (
        f"## 项目资料\n{state['context_text'] or '（未检索到相关资料）'}"
        f"{history_text}\n\n## 用户问题\n{state['question']}"
    )
    # SSE 层按 tags=["answer"] 过滤，只转发答案流
    await llm.ainvoke(
        [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)],
        config={"tags": ["answer"]},
    )
    return {}


def build_qa_graph():
    graph = StateGraph(QAState)
    graph.add_node("understand", understand_node)   # M9：原 rewrite + classify
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_edge(START, "understand")
    graph.add_edge("understand", "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


qa_graph = build_qa_graph()
