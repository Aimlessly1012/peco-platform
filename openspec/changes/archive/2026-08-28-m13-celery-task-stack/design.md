## Context

索引任务现跑在 FastAPI 进程内：`asyncio.create_task(run_index_job)`，CPU 密集段 `to_thread` 进线程池；任务状态持久化在 IndexJob 表（Postgres）；进度经进程内 progress_broker 以 SSE 推给浏览器（M9）；仓库 clone 在本地盘 `data/repos`；嵌入/摘要调硅基流动云端 API。已知缺陷：进程重启把 RUNNING 任务标 stale-failed，需人工重新触发。

服务器：腾讯云东京 3.6G 内存单机，available ~1.8G。**实测内存账（2026-08-25 在本机测得）**：

| 组件 | 空载实测 | 运行区间 |
|---|---|---|
| RabbitMQ 3.13-alpine | 128MB | 130~250MB |
| MinIO | 68MB | 70~300MB |
| worker（import 全套后端依赖的进程 RSS） | 222MB | 基线 ~250MB，索引大仓时 400~600MB |

方案对比后用户选定完整栈（就地补强 0MB / Celery+Redis 精简 ~265MB / 完整栈 450~800MB），动机含作品集的架构展示价值，风险已知情。

## Goals / Non-Goals

**Goals:**
- 索引任务出进程：API 与任务互不拖累，worker 可单独限内存、单独重启
- 重启不丢任务：RUNNING 任务在 worker 重启后自动续跑，废除人工重触发
- 完整可展示的 Celery + RabbitMQ + MinIO 栈，且在 3.6G 单机上有明确内存护栏
- 前端零改动：SSE 进度契约（事件名、载荷结构）保持不变

**Non-Goals:**
- 不做多机/多 worker 横向扩展（单 worker、concurrency=1）
- 不把 repos 工作副本迁到 MinIO——git pull 与 tree-sitter 解析必须本地文件系统
- 不改聊天/报告生成链路（仍是请求内 SSE 流式，不入队）
- 不上 Flower 等监控面板（内存预算外，见 Open Questions）

## Decisions

**D1 Celery 同步任务壳包住现有 async pipeline**：task 入口 `asyncio.run(run_index_job(...))`，pipeline 主体一行不改。每任务独立事件循环，避免 Celery prefork 与长驻 loop 的兼容坑。备选「重写为同步」工作量大且退化，「换 arq（asyncio 原生）」与选定的 RabbitMQ 栈不匹配（arq 只支持 Redis）。

**D2 `--concurrency=1` + `--max-tasks-per-child=8`**：索引本就该串行（嵌入 API 限速、Neo4j 单机写入），且每 prefork 子进程 ~250MB，默认按核数 fork 会把内存账翻倍。max-tasks-per-child 定期换子进程，兜底 tree-sitter/驱动的缓慢泄漏。

**D3 broker=RabbitMQ，result backend=Postgres（SQLAlchemy）**：复用现有 DB，不为 result 再引组件。**IndexJob 表仍是任务状态唯一事实源**（前端/API 只读它）；Celery result 仅供框架层排障。队列与消息均 durable/persistent，RabbitMQ 重启不丢投递。

**D4 进度事件经 RabbitMQ fanout exchange 跨进程**：worker 发布进度 → API 进程消费并转发 SSE。progress_broker 保留同一对外接口，仅替换传输层，浏览器契约不变。备选 Postgres LISTEN/NOTIFY 可行，但既有 RabbitMQ 就不再分裂通道。

**D5 MinIO 职责界定**：只存两类真实产物——①理解报告导出件 ②索引完成后的解析产物归档（chunk/模块统计快照）。工作文件一律本地盘。这是对「单机上 MinIO 天然没位置」的诚实回应：给它真实但非关键路径的职责，桶不可用不阻塞索引主流程（归档失败降级为 warning）。

**D6 重启恢复语义**：任务 `acks_late=True`——worker 挂掉未 ack 的消息由 RabbitMQ 重投递，配合 pipeline 已有的增量语义（重跑从缓存/已入库数据快速跳过）实现自动续跑。`main.py` 的 stale 恢复逻辑改写：启动时发现无对应在途消息的孤儿 RUNNING job 才重新入队（而非标 failed）。

**D7 内存护栏（写死在 compose）**：rabbitmq `mem_limit: 256m` + `vm_memory_high_watermark.absolute 192MB`；minio `mem_limit: 256m`；worker `mem_limit: 768m`。超限被杀的是单容器且会被 compose 拉起，保护 db/neo4j/backend 不被 OOM killer 波及。

## Risks / Trade-offs

- [索引大仓时全机内存吃紧，OOM 边缘] → 三容器硬性 mem_limit；worker 独立被杀不影响 API；任务由重投递恢复；上线后用 `docker stats` 观察一周再定是否升配
- [RabbitMQ 重启丢消息] → durable queue + persistent delivery + acks_late，验收含「kill worker 后任务自动续跑」场景
- [Celery 与 asyncio 混用的事件循环坑] → 每任务 `asyncio.run` 新建干净 loop；数据库/Neo4j 连接在任务内创建、任务尾关闭，不跨任务复用
- [MinIO 凭据泄漏] → 凭据只进服务器 `.env`；`.env.example` 用占位符（历史上已拦 4 次 key 泄漏，提交前照例 grep）
- [部署复杂度上升，3 个新服务] → compose 一把梭 + server-notes 回填运维实况；回滚 = 回退 compose 与镜像 tag

## Migration Plan

1. 本地：compose 起 rabbitmq/minio/worker，全量回归（547 测试 + 新增队列/存储测试）
2. 服务器：拉起三个新容器（此时旧路径仍在跑）→ 部署新 backend（投递切到 Celery）→ 验证「触发索引 → worker 执行 → SSE 进度 → 成功」全链路
3. 验收含破坏性场景：索引中途 `docker restart` worker，任务须自动续跑至成功
4. 回滚：backend 镜像回退上一 tag（进程内路径代码保留一个版本），三个新容器停掉即可，数据无迁移

## Open Questions

- Flower 监控面板（+~80MB）：首版不上，靠 IndexJob 表 + `docker logs`；作品集展示若需要再评估
- MinIO 归档产物保留策略（条数/天数上限）：首版不限，观察占用后定
