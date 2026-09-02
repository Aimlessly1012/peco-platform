# 任务队列

## Purpose
索引任务的入队、执行、重试、重启恢复与并发控制。M13 起由 Celery + RabbitMQ 承担，worker 跑在独立容器，进度经数据库跨进程共享并以 SSE 推送到前端。

## Requirements

### Requirement: 任务出进程执行
索引任务 SHALL 由独立 Celery worker 容器执行（broker 为 RabbitMQ），API 进程仅投递任务并立即返回；触发索引的 API 契约（请求/响应/状态码）SHALL 与进程内时代保持不变。

#### Scenario: 触发索引即入队
- **WHEN** 用户对项目触发索引
- **THEN** API 创建 IndexJob 记录并投递 Celery 任务后立即返回，任务在 worker 容器内执行

#### Scenario: worker 与 API 故障隔离
- **WHEN** worker 容器因内存超限被杀
- **THEN** API 进程不受影响，聊天与项目管理接口正常响应

### Requirement: 串行并发控制
worker SHALL 以 concurrency=1 运行，同一时刻至多执行一个索引任务；后续任务 SHALL 在队列中等待而非并行执行。

#### Scenario: 两个项目先后触发索引
- **WHEN** 项目 A 索引执行中，用户触发项目 B 的索引
- **THEN** B 的任务保持排队（IndexJob 为 pending），A 完成后 B 自动开始

### Requirement: 重启自动续跑
任务消息 SHALL 配置 durable 队列、persistent 投递与 acks_late；worker 进程中断时未完成任务 SHALL 由 broker 重投递并自动续跑，SHALL NOT 要求人工重新触发。

#### Scenario: 索引中途 worker 重启
- **WHEN** 索引任务执行中 worker 容器被重启
- **THEN** 任务被重投递并自动继续执行至成功，IndexJob 最终为 succeeded

#### Scenario: 启动时孤儿任务回收
- **WHEN** backend 启动时发现 RUNNING 状态但无在途消息的 IndexJob
- **THEN** 该任务被重新入队执行，而非标记为 failed

### Requirement: 任务状态单一事实源
IndexJob 表 SHALL 保持为任务状态的唯一事实源；API 与前端 SHALL 仅从 IndexJob 读取状态；Celery result backend 仅用于框架层排障，SHALL NOT 成为业务读取路径。

#### Scenario: 状态查询不依赖 Celery
- **WHEN** 前端查询项目索引状态
- **THEN** 数据来自 IndexJob 表，RabbitMQ 或 result backend 不可用不影响状态查询

### Requirement: 进度事件跨进程交付
worker 产生的进度事件 SHALL 经 RabbitMQ fanout 交付到 API 进程并转发 SSE；浏览器侧 SSE 契约（事件名与载荷结构）SHALL 与 M9 保持一致。

#### Scenario: 跨进程进度实时可见
- **WHEN** worker 内任务从 parse 进入 summarize 阶段
- **THEN** 浏览器通过既有 SSE 连接收到与 M9 同构的 progress 事件
