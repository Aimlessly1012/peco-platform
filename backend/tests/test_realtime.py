"""实时进度与聊天阶段单测（M9 B1-B4）。"""
import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from app.models.tables import IndexJob, JobStage, JobStatus, Project, ProjectStatus
from app.services.ingest.progress_broker import (
    ProgressBroker,
    is_terminal,
    job_event,
)
from app.services.qa.workflow import parse_understanding, understand_node


# ---------------- B1 broker ----------------


def fake_job(**overrides):
    base = {
        "id": uuid.uuid4(), "status": JobStatus.RUNNING, "stage": JobStage.EMBED,
        "progress": 60, "stats_json": {"chunks": 10}, "error_text": None, "kind": "full",
    }
    return SimpleNamespace(**{**base, **overrides})


async def test_publish_reaches_subscriber():
    broker = ProgressBroker()
    with broker.subscribe("p1") as queue:
        broker.publish("p1", {"progress": 42})
        assert await asyncio.wait_for(queue.get(), timeout=1) == {"progress": 42}


async def test_publish_fans_out_to_all_subscribers():
    """同一项目多个页面/标签页同时看进度。"""
    broker = ProgressBroker()
    with broker.subscribe("p1") as q1, broker.subscribe("p1") as q2:
        broker.publish("p1", {"progress": 1})
        assert q1.get_nowait() == {"progress": 1}
        assert q2.get_nowait() == {"progress": 1}


async def test_publish_isolated_per_project():
    broker = ProgressBroker()
    with broker.subscribe("p1") as q1, broker.subscribe("p2") as q2:
        broker.publish("p1", {"progress": 1})
        assert q1.qsize() == 1
        assert q2.qsize() == 0


def test_publish_without_subscribers_is_noop():
    """没人订阅时 publish 必须直接返回——索引管道不能因为没人看就卡住。"""
    broker = ProgressBroker()
    broker.publish("nobody", {"progress": 1})     # 不抛异常即可
    assert broker.subscriber_count("nobody") == 0


async def test_full_queue_drops_oldest_not_newest():
    """满队列丢最旧帧：新进度比旧进度有价值，而且绝不能阻塞 publish。"""
    broker = ProgressBroker(maxsize=3)
    with broker.subscribe("p1") as queue:
        for i in range(6):
            broker.publish("p1", {"progress": i})

        drained = [queue.get_nowait() for _ in range(queue.qsize())]

    assert len(drained) == 3
    assert [e["progress"] for e in drained] == [3, 4, 5]   # 保留最新三帧
    assert broker.dropped == 3


async def test_publish_never_blocks_on_full_queue():
    """哪怕订阅者一直不读，publish 也要立刻返回。"""
    broker = ProgressBroker(maxsize=2)
    with broker.subscribe("p1"):
        await asyncio.wait_for(
            asyncio.to_thread(lambda: [broker.publish("p1", {"i": i}) for i in range(500)]),
            timeout=2,
        )


async def test_unsubscribe_cleans_up():
    broker = ProgressBroker()
    with broker.subscribe("p1"):
        assert broker.subscriber_count("p1") == 1
    assert broker.subscriber_count("p1") == 0
    assert "p1" not in broker._subscribers        # 不留空集合


async def test_unsubscribe_on_exception():
    broker = ProgressBroker()
    with pytest.raises(RuntimeError):
        with broker.subscribe("p1"):
            raise RuntimeError("boom")
    assert broker.subscriber_count("p1") == 0


def test_job_event_shape():
    job = fake_job()
    event = job_event(job)
    assert set(event) == {"job_id", "status", "stage", "progress", "stats", "error_text", "kind"}
    assert event["stage"] == JobStage.EMBED
    assert event["stats"] == {"chunks": 10}


@pytest.mark.parametrize(
    "status,expect",
    [("succeeded", True), ("failed", True), ("running", False), ("idle", False)],
)
def test_is_terminal(status, expect):
    assert is_terminal({"status": status}) is expect


# ---------------- B2 SSE 端点 ----------------


def parse_sse(text: str) -> list[dict]:
    """按 data: 行解析 SSE（ping 行不含 data，自动跳过）。"""
    return [
        json.loads(line[len("data:"):].strip())
        for line in text.splitlines()
        if line.startswith("data:") and line[len("data:"):].strip()
    ]


async def seed_project(test_db, status=ProjectStatus.READY) -> uuid.UUID:
    async with test_db() as session:
        project = Project(name="p", git_url="https://example.com/x.git", status=status)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project.id


async def seed_job(test_db, project_id, **overrides) -> uuid.UUID:
    async with test_db() as session:
        job = IndexJob(project_id=project_id, kind="full", **overrides)
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job.id


async def test_progress_requires_login(anon_client, test_db):
    pid = await seed_project(test_db)
    resp = await anon_client.get(f"/projects/{pid}/progress")
    assert resp.status_code == 401


async def test_progress_unknown_project_404(api_client):
    resp = await api_client.get(f"/projects/{uuid.uuid4()}/progress")
    assert resp.status_code == 404


async def test_progress_no_job_closes_immediately(api_client, test_db):
    """spec: 没有任务时推一条 idle 就关流，不吊着连接。"""
    pid = await seed_project(test_db)

    resp = await api_client.get(f"/projects/{pid}/progress")

    assert resp.status_code == 200
    events = parse_sse(resp.text)
    assert events == [{"status": "idle"}]


async def test_progress_terminal_job_snapshot_then_close(api_client, test_db):
    """已完成的任务：推完快照直接关流（不必等增量）。"""
    pid = await seed_project(test_db)
    await seed_job(test_db, pid, status=JobStatus.SUCCEEDED, stage=JobStage.REPORT, progress=100)

    resp = await api_client.get(f"/projects/{pid}/progress")

    events = parse_sse(resp.text)
    assert len(events) == 1
    assert events[0]["status"] == "succeeded"
    assert events[0]["progress"] == 100


async def test_progress_snapshot_then_increments_then_close(api_client, test_db):
    """完整链路：快照 → 增量 → 终态关流。"""
    from app.services.ingest.progress_broker import progress_broker

    pid = await seed_project(test_db, ProjectStatus.INDEXING)
    job_id = await seed_job(
        test_db, pid, status=JobStatus.RUNNING, stage=JobStage.PARSE, progress=20
    )

    async def push_later():
        # 等端点订阅完再推：订阅发生在首个 yield 之前
        for _ in range(50):
            if progress_broker.subscriber_count(str(pid)):
                break
            await asyncio.sleep(0.01)
        progress_broker.publish(str(pid), {
            "job_id": str(job_id), "status": "running", "stage": "embed",
            "progress": 70, "stats": {}, "error_text": None, "kind": "full",
        })
        progress_broker.publish(str(pid), {
            "job_id": str(job_id), "status": "succeeded", "stage": "report",
            "progress": 100, "stats": {}, "error_text": None, "kind": "full",
        })

    pusher = asyncio.create_task(push_later())
    resp = await asyncio.wait_for(
        api_client.get(f"/projects/{pid}/progress"), timeout=10
    )
    await pusher

    events = parse_sse(resp.text)
    assert [e["progress"] for e in events] == [20, 70, 100]
    assert events[0]["stage"] == "parse"          # 首帧是 DB 快照
    assert events[-1]["status"] == "succeeded"    # 终态即关流


async def test_pipeline_update_publishes_progress(test_db):
    """B1 接入点：_update_job 是所有进度变更的必经之路，挂它才不会漏推。"""
    from app.services.ingest.pipeline import _update_job
    from app.services.ingest.progress_broker import progress_broker

    pid = await seed_project(test_db)
    job_id = await seed_job(test_db, pid, status=JobStatus.RUNNING)

    with progress_broker.subscribe(str(pid)) as queue:
        await _update_job(job_id, stage=JobStage.EMBED, progress=66)

        event = queue.get_nowait()
    assert event["stage"] == JobStage.EMBED
    assert event["progress"] == 66
    assert event["status"] == JobStatus.RUNNING


async def test_pipeline_finish_publishes_terminal(test_db):
    from app.services.ingest.pipeline import _finish
    from app.services.ingest.progress_broker import progress_broker

    pid = await seed_project(test_db)
    job_id = await seed_job(test_db, pid, status=JobStatus.RUNNING)

    with progress_broker.subscribe(str(pid)) as queue:
        await _finish(job_id, pid, error="炸了")

        events = [queue.get_nowait() for _ in range(queue.qsize())]
    assert events[-1]["status"] == JobStatus.FAILED
    assert events[-1]["error_text"] == "炸了"
    assert is_terminal(events[-1])


# ---------------- B3 stage 事件 ----------------


class FakeGraph:
    """回放 LangGraph 事件流：节点开始 → token → retrieve 结束。"""

    def __init__(self, events):
        self.events = events

    async def astream_events(self, inputs, version=None):
        for event in self.events:
            yield event


def chain_start(name):
    return {"event": "on_chain_start", "name": name, "data": {}}


def token(text):
    return {"event": "on_chat_model_stream", "tags": ["answer"],
            "data": {"chunk": SimpleNamespace(content=text)}}


async def seed_chat(test_db, api_client):
    pid = await seed_project(test_db)
    resp = await api_client.post(f"/projects/{pid}/sessions", json={"title": "t"})
    return resp.json()["id"]


def sse_events(text: str) -> list[tuple[str, dict]]:
    """解析出 (event 名, data) 序列。"""
    out, current = [], None
    for line in text.splitlines():
        if line.startswith("event:"):
            current = line[len("event:"):].strip()
        elif line.startswith("data:") and current:
            raw = line[len("data:"):].strip()
            out.append((current, json.loads(raw) if raw else {}))
            current = None
    return out


async def test_stage_events_in_order(api_client, test_db, monkeypatch):
    """spec: 事件序 stage* → token* → citations → done。"""
    session_id = await seed_chat(test_db, api_client)
    monkeypatch.setattr("app.api.chat.qa_graph", FakeGraph([
        chain_start("understand"),
        chain_start("retrieve"),
        {"event": "on_chain_end", "name": "retrieve", "data": {"output": {"items": []}}},
        chain_start("generate"),
        token("答"), token("案"),
    ]))

    resp = await api_client.post(f"/sessions/{session_id}/ask", json={"question": "q"})

    names = [name for name, _ in sse_events(resp.text)]
    assert names == ["stage", "stage", "stage", "token", "token", "citations", "done"]
    stages = [d["stage"] for name, d in sse_events(resp.text) if name == "stage"]
    assert stages == ["understand", "retrieve", "generate"]


async def test_unknown_nodes_not_reported_as_stage(api_client, test_db, monkeypatch):
    """图内部节点（__start__ / RunnableSequence 等）不该冒出来当阶段。"""
    session_id = await seed_chat(test_db, api_client)
    monkeypatch.setattr("app.api.chat.qa_graph", FakeGraph([
        chain_start("__start__"),
        chain_start("RunnableSequence"),
        chain_start("LangGraph"),
        chain_start("retrieve"),
        token("x"),
    ]))

    resp = await api_client.post(f"/sessions/{session_id}/ask", json={"question": "q"})

    stages = [d["stage"] for name, d in sse_events(resp.text) if name == "stage"]
    assert stages == ["retrieve"]


async def test_stage_reported_once_per_node(api_client, test_db, monkeypatch):
    """同一节点重复 on_chain_start（重试/子图）只报一次，前端文案不闪。"""
    session_id = await seed_chat(test_db, api_client)
    monkeypatch.setattr("app.api.chat.qa_graph", FakeGraph([
        chain_start("retrieve"), chain_start("retrieve"), chain_start("retrieve"),
        token("x"),
    ]))

    resp = await api_client.post(f"/sessions/{session_id}/ask", json={"question": "q"})

    stages = [d["stage"] for name, d in sse_events(resp.text) if name == "stage"]
    assert stages == ["retrieve"]


async def test_stage_does_not_disturb_token_stream(api_client, test_db, monkeypatch):
    """内部节点的 token 仍被 tags 过滤挡住，stage 不影响答案内容。"""
    session_id = await seed_chat(test_db, api_client)
    monkeypatch.setattr("app.api.chat.qa_graph", FakeGraph([
        chain_start("understand"),
        {"event": "on_chat_model_stream", "tags": ["internal"],
         "data": {"chunk": SimpleNamespace(content="不该出现")}},
        chain_start("generate"),
        token("正文"),
    ]))

    resp = await api_client.post(f"/sessions/{session_id}/ask", json={"question": "q"})

    tokens = [d["t"] for name, d in sse_events(resp.text) if name == "token"]
    assert tokens == ["正文"]


# ---------------- B4 合并调用 ----------------


class FakeLLM:
    def __init__(self, reply):
        self.reply = reply

    async def ainvoke(self, messages, config=None):
        if isinstance(self.reply, Exception):
            raise self.reply
        return SimpleNamespace(content=self.reply)


@pytest.mark.parametrize(
    "raw,expect",
    [
        ('{"rewritten": "订单怎么创建", "type": "local"}', ("订单怎么创建", "local")),
        ('{"rewritten": "整体架构", "type": "global"}', ("整体架构", "global")),
        ('{"rewritten": "改它影响啥", "type": "impact"}', ("改它影响啥", "impact")),
        ('```json\n{"rewritten": "X", "type": "local"}\n```', ("X", "local")),
        ('好的：{"rewritten": "Y", "type": "GLOBAL"} 以上', ("Y", "global")),
    ],
)
def test_parse_understanding_ok(raw, expect):
    assert parse_understanding(raw, "原问题") == expect


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "完全不是 JSON", "{坏 JSON", "[1,2,3]", '{"type": "local"}',
     '{"rewritten": "", "type": "local"}'],
)
def test_parse_understanding_falls_back_to_original(raw):
    """spec: 解析失败降级原问题 + local——与合并前两个节点各自的降级一致。"""
    rewritten, qtype = parse_understanding(raw, "原问题")
    assert rewritten == "原问题"
    assert qtype == "local"


def test_parse_understanding_unknown_type_defaults_local():
    assert parse_understanding('{"rewritten": "X", "type": "什么类型"}', "原") == ("X", "local")


async def test_understand_node_success(monkeypatch):
    monkeypatch.setattr(
        "app.services.qa.workflow.build_llm",
        lambda streaming=True: FakeLLM('{"rewritten": "订单模块的取消逻辑", "type": "local"}'),
    )

    out = await understand_node({"question": "那它的取消逻辑呢", "history": [
        {"role": "user", "content": "订单模块怎么实现的"}
    ]})

    assert out == {"rewritten_question": "订单模块的取消逻辑", "question_type": "local"}


async def test_understand_node_llm_failure_degrades(monkeypatch):
    monkeypatch.setattr(
        "app.services.qa.workflow.build_llm",
        lambda streaming=True: FakeLLM(RuntimeError("上游 500")),
    )

    out = await understand_node({"question": "原问题"})

    assert out == {"rewritten_question": "原问题", "question_type": "local"}


async def test_understand_node_is_single_llm_call(monkeypatch):
    """合并的意义就在于只调一次——退回两次的话首答又要多等一轮。"""
    calls = []

    def build(streaming=True):
        calls.append(streaming)
        return FakeLLM('{"rewritten": "X", "type": "local"}')

    monkeypatch.setattr("app.services.qa.workflow.build_llm", build)
    await understand_node({"question": "q"})

    assert len(calls) == 1


async def test_graph_has_three_nodes():
    """图结构：understand → retrieve → generate。"""
    from app.services.qa.workflow import build_qa_graph

    graph = build_qa_graph()
    nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}
    assert nodes == {"understand", "retrieve", "generate"}
