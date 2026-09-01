"""任务队列语义单测（M13 5.1/5.2 + 3.1 进度跨进程）。

真正的"kill worker 后自动续跑"要真 RabbitMQ + 真 worker，属于 6.2 部署验收；
这里钉住的是让那件事成立的结构：幂等门、投递切换、孤儿回收、进度镜像契约。
"""
import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.tables import IndexJob, JobStage, JobStatus, Project, ProjectStatus
from app.services.ingest import celery_tasks
from app.services.ingest.celery_tasks import RESULT_DONE, RESULT_SKIPPED
from app.services.ingest.progress_broker import ProgressBroker, job_event
from app.services.ingest.progress_transport import ProgressConsumer, ProgressMirror


async def make_project(test_db, status=ProjectStatus.READY) -> uuid.UUID:
    async with test_db() as session:
        project = Project(name="p", git_url="https://example.com/x.git", status=status)
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project.id


async def make_job(test_db, project_id, **overrides) -> uuid.UUID:
    async with test_db() as session:
        job = IndexJob(project_id=project_id, kind="full", **overrides)
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job.id


@pytest.fixture
def pipeline_spy(monkeypatch):
    """替掉 run_index_job：这里测的是壳，不是管道。"""
    calls = []

    async def fake_run(job_id, project_id, mode, depth):
        calls.append((job_id, project_id, mode, depth))

    monkeypatch.setattr("app.services.ingest.pipeline.run_index_job", fake_run)
    return calls


@pytest.fixture
def cleanup_spy(monkeypatch):
    """盯住任务尾的清池动作（asyncio.run 跨任务复用连接池必炸，见 celery_tasks 注释）。"""
    done = []

    async def fake_dispose():
        done.append("engine")

    async def fake_close_driver():
        done.append("driver")

    monkeypatch.setattr(
        celery_tasks.core_db, "engine", SimpleNamespace(dispose=fake_dispose)
    )
    monkeypatch.setattr(celery_tasks.graph_client, "close_driver", fake_close_driver)
    return done


# ---------------- 幂等门（重复投递无害化）----------------


@pytest.mark.parametrize("status", [JobStatus.SUCCEEDED, JobStatus.FAILED])
async def test_terminal_job_skips_pipeline(
    test_db, pipeline_spy, cleanup_spy, status
):
    """spec 场景: 重投递的消息落到已终态的任务 → 直接返回，不重跑一遍索引。"""
    pid = await make_project(test_db)
    job_id = await make_job(test_db, pid, status=status)

    result = await celery_tasks._run_with_cleanup(job_id, pid, "auto", "deep")

    assert result == RESULT_SKIPPED
    assert pipeline_spy == []


async def test_missing_job_skips_pipeline(test_db, pipeline_spy, cleanup_spy):
    """项目被删后 broker 里还压着消息：查不到 job 就当没这回事。"""
    pid = await make_project(test_db)

    result = await celery_tasks._run_with_cleanup(
        uuid.uuid4(), pid, "auto", "deep"
    )

    assert result == RESULT_SKIPPED
    assert pipeline_spy == []


async def test_running_job_is_executed(test_db, pipeline_spy, cleanup_spy):
    pid = await make_project(test_db)
    job_id = await make_job(test_db, pid, status=JobStatus.RUNNING)

    result = await celery_tasks._run_with_cleanup(job_id, pid, "full", "fast")

    assert result == RESULT_DONE
    assert pipeline_spy == [(job_id, pid, "full", "fast")]


# ---------------- 事件循环清池（最容易踩的坑）----------------


async def test_pools_disposed_after_task(test_db, pipeline_spy, cleanup_spy):
    """每任务一个新 asyncio.run，池里留着上个循环的连接就会炸 different loop。"""
    pid = await make_project(test_db)
    job_id = await make_job(test_db, pid)

    await celery_tasks._run_with_cleanup(job_id, pid, "auto", "deep")

    assert cleanup_spy == ["engine", "driver"]


async def test_pools_disposed_even_when_pipeline_raises(
    test_db, cleanup_spy, monkeypatch
):
    """失败任务更要清池——否则一次异常就污染后续所有任务。"""

    async def boom(*_args):
        raise RuntimeError("管道炸了")

    monkeypatch.setattr("app.services.ingest.pipeline.run_index_job", boom)
    pid = await make_project(test_db)
    job_id = await make_job(test_db, pid)

    with pytest.raises(RuntimeError):
        await celery_tasks._run_with_cleanup(job_id, pid, "auto", "deep")

    assert cleanup_spy == ["engine", "driver"]


async def test_skipped_task_also_disposes_pools(test_db, pipeline_spy, cleanup_spy):
    pid = await make_project(test_db)
    job_id = await make_job(test_db, pid, status=JobStatus.SUCCEEDED)

    await celery_tasks._run_with_cleanup(job_id, pid, "auto", "deep")

    assert cleanup_spy == ["engine", "driver"]


# ---------------- Celery 配置（串行与重投递的结构前提）----------------


def test_celery_config_supports_restart_resume():
    """acks_late + reject_on_worker_lost + prefetch=1 是"重启续跑"的根基，别被"优化"掉。"""
    conf = celery_tasks.celery_app.conf

    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_default_queue == "indexing"


def test_index_task_registered():
    assert celery_tasks.TASK_NAME in celery_tasks.celery_app.tasks


# ---------------- 投递切换（生产回滚开关）----------------


@pytest.fixture
def delay_spy(monkeypatch):
    calls = []

    def fake_enqueue(job_id, project_id, mode, depth):
        calls.append((job_id, project_id, mode, depth))
        return "celery-task-id"

    monkeypatch.setattr(celery_tasks, "enqueue_index_job", fake_enqueue)
    return calls


async def test_disabled_runs_in_process(test_db, monkeypatch, pipeline_spy, delay_spy):
    """spec 回滚方案: TASK_QUEUE_ENABLED=false 时行为与 M12 完全一致（本进程跑协程）。"""
    from app.services.ingest import pipeline

    monkeypatch.setattr(settings, "task_queue_enabled", False)
    pid = await make_project(test_db)

    job = await pipeline.start_index_job(pid, "auto", "deep")
    await asyncio.sleep(0)      # 让 create_task 排上的协程跑一轮

    assert job is not None
    assert pipeline_spy == [(job.id, pid, "auto", "deep")]
    assert delay_spy == []


async def test_enabled_dispatches_to_worker(test_db, monkeypatch, pipeline_spy, delay_spy):
    """spec 场景: 触发索引即入队——API 建完 IndexJob 就投递，不在本进程跑。"""
    from app.services.ingest import pipeline

    monkeypatch.setattr(settings, "task_queue_enabled", True)
    pid = await make_project(test_db)

    job = await pipeline.start_index_job(pid, "full", "fast")
    await asyncio.sleep(0)

    assert pipeline_spy == []                  # 本进程一点活没干
    assert delay_spy == [(job.id, pid, "full", "fast")]
    assert job.status == JobStatus.RUNNING


async def test_enqueue_failure_discards_job_and_returns_503(
    api_client, test_db, monkeypatch
):
    """broker 不可用：不能返回 202 让前端空等，也不能留下把项目卡在 409 的 RUNNING 记录。"""
    monkeypatch.setattr(settings, "task_queue_enabled", True)

    def boom(*_args):
        raise OSError("connection refused")

    monkeypatch.setattr(celery_tasks, "enqueue_index_job", boom)
    pid = await make_project(test_db, status=ProjectStatus.READY)

    resp = await api_client.post(f"/projects/{pid}/index")

    assert resp.status_code == 503
    assert "任务队列不可用" in resp.json()["detail"]
    async with test_db() as session:
        assert (await session.scalars(select(IndexJob))).all() == []
        project = await session.get(Project, pid)
        assert project.status == ProjectStatus.READY   # 状态回退，没卡在 indexing


async def test_running_job_still_conflicts(api_client, test_db, monkeypatch, delay_spy):
    """入队与否不改变"一个项目同时只跑一个任务"的语义。"""
    monkeypatch.setattr(settings, "task_queue_enabled", True)
    pid = await make_project(test_db)
    await make_job(test_db, pid, status=JobStatus.RUNNING)

    resp = await api_client.post(f"/projects/{pid}/index")

    assert resp.status_code == 409
    assert delay_spy == []


async def test_job_status_readable_without_broker(api_client, test_db, monkeypatch):
    """spec 场景: 状态查询不依赖 Celery——IndexJob 表是唯一事实源。"""
    monkeypatch.setattr(settings, "task_queue_enabled", True)

    def boom(*_args):
        raise OSError("broker down")

    monkeypatch.setattr(celery_tasks, "enqueue_index_job", boom)
    pid = await make_project(test_db)
    await make_job(test_db, pid, status=JobStatus.RUNNING, progress=55,
                   stage=JobStage.EMBED)

    resp = await api_client.get(f"/projects/{pid}/jobs/latest")

    assert resp.status_code == 200
    assert resp.json()["progress"] == 55
    assert resp.json()["stage"] == JobStage.EMBED


# ---------------- 孤儿回收 ----------------


async def test_stale_running_job_is_requeued(test_db, monkeypatch, delay_spy):
    """spec 场景: 启动时发现孤儿 RUNNING 任务 → 重新入队，而不是标 failed。"""
    import app.main as main

    monkeypatch.setattr(settings, "task_queue_enabled", True)
    pid = await make_project(test_db, status=ProjectStatus.INDEXING)
    job_id = await make_job(
        test_db, pid, status=JobStatus.RUNNING,
        stats_json={"requested_mode": "full", "requested_depth": "fast"},
    )

    await main._recover_stale_jobs()

    assert delay_spy == [(job_id, pid, "full", "fast")]
    async with test_db() as session:
        job = await session.get(IndexJob, job_id)
        assert job.status == JobStatus.RUNNING       # 没被标 failed
        assert job.error_text is None


async def test_requeue_falls_back_to_auto_when_params_lost(
    test_db, monkeypatch, delay_spy
):
    """管道跑到一半时 stats 已被真实统计覆盖，请求参数只能从 actual mode 推。"""
    import app.main as main

    monkeypatch.setattr(settings, "task_queue_enabled", True)
    pid = await make_project(test_db, status=ProjectStatus.INDEXING)
    job_id = await make_job(
        test_db, pid, status=JobStatus.RUNNING,
        stats_json={"mode": "incremental", "depth": "deep", "files_parsed": 12},
    )

    await main._recover_stale_jobs()

    assert delay_spy == [(job_id, pid, "auto", "deep")]


async def test_requeue_failure_does_not_block_startup(test_db, monkeypatch):
    """broker 还没起来不能让 API 起不来——记 warning，任务留着下次启动再捞。"""
    import app.main as main

    monkeypatch.setattr(settings, "task_queue_enabled", True)

    def boom(*_args):
        raise OSError("broker down")

    monkeypatch.setattr(celery_tasks, "enqueue_index_job", boom)
    pid = await make_project(test_db, status=ProjectStatus.INDEXING)
    job_id = await make_job(test_db, pid, status=JobStatus.RUNNING)

    await main._recover_stale_jobs()      # 不抛异常即达标

    async with test_db() as session:
        assert (await session.get(IndexJob, job_id)).status == JobStatus.RUNNING


async def test_stale_jobs_still_failed_when_queue_disabled(test_db, monkeypatch):
    """关掉队列时保持 M12 行为：标 failed(stale)，项目状态回退。"""
    import app.main as main

    monkeypatch.setattr(settings, "task_queue_enabled", False)
    pid = await make_project(test_db, status=ProjectStatus.INDEXING)
    job_id = await make_job(test_db, pid, status=JobStatus.RUNNING)

    await main._recover_stale_jobs()

    async with test_db() as session:
        job = await session.get(IndexJob, job_id)
        assert job.status == JobStatus.FAILED
        assert "stale" in job.error_text
        assert (await session.get(Project, pid)).status == ProjectStatus.FAILED


# ---------------- 进度镜像（worker 侧）----------------


def test_mirror_gets_every_frame_and_local_delivery_survives():
    """mirror 是旁路不是替代：装了它，进程内订阅者照收不误。"""
    broker = ProgressBroker()
    seen = []
    broker.set_mirror(lambda pid, event: seen.append((pid, event)))

    with broker.subscribe("p1") as queue:
        broker.publish("p1", {"progress": 42})

        assert queue.get_nowait() == {"progress": 42}
    assert seen == [("p1", {"progress": 42})]


def test_mirror_receives_frames_without_local_subscribers():
    """worker 进程里没人订阅，但帧必须发出去——API 进程那边才有人在等。"""
    broker = ProgressBroker()
    seen = []
    broker.set_mirror(lambda pid, event: seen.append((pid, event)))

    broker.publish("p1", {"progress": 7})

    assert seen == [("p1", {"progress": 7})]


def test_mirror_failure_does_not_break_pipeline():
    """传输层坏掉绝不能反噬索引管道。"""
    broker = ProgressBroker()

    def broken(_pid, _event):
        raise ConnectionError("broker down")

    broker.set_mirror(broken)
    with broker.subscribe("p1") as queue:
        broker.publish("p1", {"progress": 1})      # 不抛异常
        assert queue.get_nowait() == {"progress": 1}


def test_mirror_drops_instead_of_blocking_when_full():
    """有界队列 + 丢帧，与 progress_broker 既有的丢帧哲学一致。"""
    mirror = ProgressMirror("amqp://unused", maxsize=2)

    for i in range(5):
        mirror.publish("p1", {"progress": i})

    assert mirror.dropped == 3     # 队列只吃下 2 帧，其余丢掉且没卡住


def test_mirror_payload_keeps_job_event_shape():
    """浏览器契约：镜像搬运的是原样的 job_event，一个字段都不能加工。"""
    mirror = ProgressMirror("amqp://unused")
    job = SimpleNamespace(
        id=uuid.uuid4(), project_id=uuid.uuid4(), status=JobStatus.RUNNING,
        stage=JobStage.SUMMARIZE, progress=33, stats_json={"chunks": 5},
        error_text=None, kind="incremental",
    )
    event = job_event(job)

    mirror.publish(str(job.project_id), event)

    payload = mirror._queue.get_nowait()
    assert payload == {"project_id": str(job.project_id), "event": event}
    assert set(payload["event"]) == {
        "job_id", "status", "stage", "progress", "stats", "error_text", "kind"
    }


# ---------------- 进度消费（API 侧）----------------


def make_consumer():
    received = []
    consumer = ProgressConsumer(
        "amqp://unused", lambda pid, event: received.append((pid, event))
    )
    return consumer, received


def test_consumer_forwards_frame_and_acks():
    consumer, received = make_consumer()
    acked = []
    message = SimpleNamespace(ack=lambda: acked.append(True))

    consumer.handle({"project_id": "p1", "event": {"progress": 9}}, message)

    assert received == [("p1", {"progress": 9})]
    assert acked == [True]


@pytest.mark.parametrize(
    "body",
    [
        {"event": {"progress": 1}},            # 缺 project_id
        {"project_id": "p1"},                  # 缺 event
        {"project_id": "p1", "event": "oops"},  # event 不是对象
        "not-a-dict",
    ],
)
def test_consumer_drops_malformed_frames(body):
    """坏帧丢掉即可，绝不能让消费循环断开——断了整台机器就没进度了。"""
    consumer, received = make_consumer()

    consumer.handle(body, SimpleNamespace(ack=lambda: None))

    assert received == []
    assert consumer.malformed == 1


async def test_cross_process_frame_reaches_sse_subscriber():
    """端到端结构：worker 的 mirror → 消费者 → API 进程 broker → SSE 订阅者。

    浏览器侧看到的仍是 M9 的 job_event 结构（spec: 进度事件跨进程交付）。
    """
    worker_broker = ProgressBroker()
    api_broker = ProgressBroker()
    wire = []
    worker_broker.set_mirror(
        lambda pid, event: wire.append({"project_id": pid, "event": event})
    )
    consumer = ProgressConsumer("amqp://unused", api_broker.publish)

    job = SimpleNamespace(
        id=uuid.uuid4(), project_id=uuid.uuid4(), status=JobStatus.RUNNING,
        stage=JobStage.SUMMARIZE, progress=30, stats_json={}, error_text=None,
        kind="full",
    )
    with api_broker.subscribe(str(job.project_id)) as queue:
        worker_broker.publish(str(job.project_id), job_event(job))   # worker 侧
        for frame in wire:                                           # 过一趟"网络"
            consumer.handle(frame)

        event = await asyncio.wait_for(queue.get(), timeout=1)

    assert event == job_event(job)
    assert event["stage"] == JobStage.SUMMARIZE
