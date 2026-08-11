"""LangGraph 问答工作流：M1 为 retrieve → generate 两节点。

State 预留 rewritten_question / question_type 字段，M2 在图前端加
rewrite / classify 节点时不改状态模型（设计 D6）。
"""
from typing import TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from app.core.config import settings
from app.services.retrieval.service import RetrievedChunk, search_chunks

SYSTEM_PROMPT = """你是代码仓库问答助手。基于给出的代码片段回答用户关于该项目的问题。

规则：
1. 只依据提供的代码片段回答，不要编造不存在的代码或文件
2. 提到具体代码时，标注出处，格式：`文件路径:起始行`
3. 片段不足以回答时，如实说明"当前检索到的代码不足以回答"，并说明已看到的相关线索
4. 用中文回答，代码保持原文"""


class QAState(TypedDict, total=False):
    project_id: str
    question: str
    history: list[dict]  # [{role, content}] 最近几轮
    # M2 扩展位：
    rewritten_question: str
    question_type: str
    # 检索与生成结果：
    chunks: list[RetrievedChunk]
    context_text: str


async def retrieve_node(state: QAState) -> QAState:
    chunks = await search_chunks(state["project_id"], state["question"])
    context_parts = [
        f"### 片段 {i + 1}: {c.file_path}:{c.start_line}-{c.end_line} "
        f"({c.symbol_type} {c.symbol})\n```{c.file_path.rsplit('.', 1)[-1]}\n{c.code}\n```"
        for i, c in enumerate(chunks)
    ]
    return {"chunks": chunks, "context_text": "\n\n".join(context_parts)}


def build_llm(streaming: bool = True) -> ChatOpenAI:
    return ChatOpenAI(
        base_url=settings.chat_base_url,
        api_key=settings.chat_api_key,
        model=settings.chat_model,
        streaming=streaming,
        temperature=0.1,
    )


async def generate_node(state: QAState) -> QAState:
    llm = build_llm()
    history_text = ""
    if state.get("history"):
        rounds = [f"{m['role']}: {m['content'][:500]}" for m in state["history"][-6:]]
        history_text = "\n\n## 对话历史（供理解指代）\n" + "\n".join(rounds)

    prompt = (
        f"## 检索到的代码片段\n{state['context_text'] or '（未检索到相关代码）'}"
        f"{history_text}\n\n## 用户问题\n{state['question']}"
    )
    # 流式 token 由调用方通过 astream_events 捕获（on_chat_model_stream）
    await llm.ainvoke(
        [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
    )
    return {}


def build_qa_graph():
    graph = StateGraph(QAState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


qa_graph = build_qa_graph()
