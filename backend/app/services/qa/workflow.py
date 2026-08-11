"""LangGraph 问答工作流（M2）：rewrite → classify → retrieve → generate。

- rewrite：有历史时把追问改写为独立问题（无历史跳过）
- classify：global|local，失败默认 local（spec: 分类失败安全回退）
- generate 的 LLM 调用带 tags=["answer"]，SSE 层只转发该标签的 token 流，
  避免 rewrite/classify 的输出混入答案。
"""
import logging
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.services.retrieval.service import (
    RetrievedItem,
    get_project_summary,
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
5. 用中文回答，代码保持原文"""

REWRITE_PROMPT = """根据对话历史，把用户的最新问题改写成一个不依赖上下文、可独立理解的完整问题。只输出改写后的问题本身，不要解释。

对话历史：
{history}

最新问题：{question}"""

CLASSIFY_PROMPT = """判断以下关于代码项目的问题属于哪一类，只输出一个词（global 或 local）：
- global：关于项目整体的——架构、技术栈、入口、整体流程、模块划分、"这个项目是干嘛的"
- local：关于具体代码的——某个函数/类/文件在哪、怎么实现、某段逻辑、某个接口的细节

例子：
"这个项目的整体架构是什么" → global
"create_order 函数在哪" → local
"登录流程怎么实现的" → global
"这个报错是哪里抛的" → local

问题：{question}"""


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


async def rewrite_node(state: QAState) -> QAState:
    if not state.get("history"):
        return {"rewritten_question": state["question"]}
    history_text = "\n".join(
        f"{m['role']}: {m['content'][:300]}" for m in state["history"][-6:]
    )
    try:
        llm = build_llm(streaming=False)
        resp = await llm.ainvoke(
            [HumanMessage(content=REWRITE_PROMPT.format(
                history=history_text, question=state["question"]
            ))],
            config={"tags": ["internal"]},
        )
        rewritten = (resp.content or "").strip()
        return {"rewritten_question": rewritten or state["question"]}
    except Exception:  # noqa: BLE001 — 改写失败退回原问题
        logger.warning("rewrite 失败，使用原问题", exc_info=True)
        return {"rewritten_question": state["question"]}


async def classify_node(state: QAState) -> QAState:
    question = state.get("rewritten_question") or state["question"]
    try:
        llm = build_llm(streaming=False)
        resp = await llm.ainvoke(
            [HumanMessage(content=CLASSIFY_PROMPT.format(question=question))],
            config={"tags": ["internal"]},
        )
        answer = (resp.content or "").strip().lower()
        qtype = "global" if "global" in answer else "local"
    except Exception:  # noqa: BLE001 — spec: 分类失败安全回退 local
        logger.warning("classify 失败，回退 local", exc_info=True)
        qtype = "local"
    return {"question_type": qtype}


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


async def retrieve_node(state: QAState) -> QAState:
    question = state.get("rewritten_question") or state["question"]
    qtype = state.get("question_type", "local")
    items = await search_layered(state["project_id"], question, qtype)

    parts = [_format_item(i + 1, item) for i, item in enumerate(items)]
    project_summary = ""
    if qtype == "global":
        project_summary = await get_project_summary(state["project_id"])
        if project_summary:
            # 不给编号：它不在 items 里，没有对应的 citation 条目，标题里写明避免模型误编号
            parts.insert(0, f"### 【项目总览】（背景信息，无编号，不要标注）\n{project_summary}")
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
    graph.add_node("rewrite", rewrite_node)
    graph.add_node("classify", classify_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_edge(START, "rewrite")
    graph.add_edge("rewrite", "classify")
    graph.add_edge("classify", "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


qa_graph = build_qa_graph()
