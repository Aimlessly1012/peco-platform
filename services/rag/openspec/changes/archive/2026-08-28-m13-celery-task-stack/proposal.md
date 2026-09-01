## Why

索引任务目前跑在 FastAPI 进程内（`asyncio.create_task`）：进程一重启，RUNNING 任务只能标成 stale-failed 等人手动重新触发；任务的 CPU/内存尖峰与 API 同进程互相拖累。同时 peco-platform 是作品集项目，任务基础设施本身就是展示面——经方案对比（就地补强 / Celery+Redis 精简 / 完整栈）后**选定 Celery + RabbitMQ + MinIO 完整栈**，接受实测得出的内存代价（常驻 +450~800MB，见 design），换取任务可靠性与完整的分布式任务架构叙事。

## What Changes

- 索引任务从 API 进程内 asyncio 任务改为 **Celery worker 独立容器**执行（`--concurrency=1`，任务内部 `asyncio.run` 复用现有 async pipeline，pipeline 主体不动）
- 新增 **RabbitMQ** 容器：Celery broker + 索引进度事件的跨进程 fanout 通道
- 新增 **MinIO** 容器：对象存储，落地两类真实产物——理解报告导出件、索引完成后的解析产物归档（repos 工作副本仍在 worker 本地盘，git/tree-sitter 必须本地文件系统）
- **BREAKING（行为改善）**：进程重启不再把 RUNNING 任务标 stale-failed——任务在 worker 重启后由 Celery 重投递自动续跑；IndexJob 表仍是任务状态的单一事实源
- M9 的 SSE 进度通道改造：progress_broker 从进程内 pub/sub 改为经 RabbitMQ 跨进程（浏览器侧 SSE 契约不变，事件名/结构不动）
- 内存护栏（3.6G 服务器硬约束）：三个新容器全部设 compose `mem_limit`，RabbitMQ 设绝对内存水位，worker 设 `--max-tasks-per-child` 防泄漏累积

## Capabilities

### New Capabilities
- `task-queue`: 索引任务的入队、执行、重试、重启恢复与并发控制（Celery + RabbitMQ）
- `artifact-storage`: 报告导出件与索引产物的对象存储（MinIO），含桶初始化与凭据管理

### Modified Capabilities
- `indexing-pipeline`: 任务执行模型与重启恢复语义变更——从「进程内执行、重启标 stale-failed」改为「worker 外执行、重启自动续跑」；进度事件从进程内广播改为跨进程通道（对前端 SSE 契约不变）

## Impact

- **后端代码**：新增 celery_app 模块与任务入口包装；`api/projects.py` 触发索引处改为投递 Celery 任务；`ingest/progress_broker.py` 跨进程化；`main.py` 的 stale 恢复逻辑改写；报告导出与产物归档接 MinIO SDK
- **部署**：compose 新增 rabbitmq / minio / worker 三服务（均带 mem_limit）；服务器常驻内存 +450~800MB（实测：RabbitMQ 空载 128MB、MinIO 空载 68MB、worker import 全套依赖 222MB）；`.env` 新增 RabbitMQ/MinIO 凭据
- **不受影响**：前端 SSE 契约、聊天/检索/MCP 链路、平台鉴权、Neo4j/Postgres 数据
