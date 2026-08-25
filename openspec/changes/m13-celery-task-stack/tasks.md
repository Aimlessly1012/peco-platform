## 1. 队列基础设施

- [x] 1.1 compose 新增 rabbitmq（3.13-alpine，mem_limit 256m，vm_memory_high_watermark.absolute 192MB，durable 数据卷）与 minio（mem_limit 256m，数据卷），凭据走 .env（.env.example 用占位符，提交前 grep 检查）
- [x] 1.2 backend 依赖加 celery[amqp] 与 minio SDK；新增 app/core/celery_app.py（broker=RabbitMQ、result backend=Postgres/SQLAlchemy、task_acks_late=True、durable/persistent 投递）
- [x] 1.3 compose 新增 worker 服务（同 backend 镜像，命令 celery worker --concurrency=1 --max-tasks-per-child=8，mem_limit 768m，挂载同一 data/repos 卷）

## 2. 任务出进程

- [x] 2.1 新增 Celery 任务壳：同步 task 入口内 asyncio.run(run_index_job(...))，每任务新建事件循环，DB/Neo4j 连接任务内创建、任务尾关闭
- [x] 2.2 api/projects.py 触发索引改为投递 Celery 任务（API 契约不变：仍先建 IndexJob 再返回）
- [x] 2.3 main.py stale 恢复逻辑改写：启动时发现无在途消息的孤儿 RUNNING job 重新入队而非标 failed
- [x] 2.4 验证 pipeline 增量语义支撑重投递续跑：重跑时已入库摘要/向量经缓存快速跳过（不足则补齐幂等性）

## 3. 进度跨进程

- [x] 3.1 progress_broker 传输层替换为 RabbitMQ fanout（worker 发布、API 消费转 SSE），对外接口与事件结构保持 M9 契约不变
- [x] 3.2 前端零改动验证：浏览器 SSE 收到的 progress 事件与改造前同构（实机对照一次）

## 4. MinIO 产物存储

- [x] 4.1 新增 storage 模块：MinIO 客户端封装 + 启动时确保桶存在
- [x] 4.2 理解报告导出件上传 MinIO 并提供按项目下载
- [x] 4.3 索引完成后解析产物快照归档；归档失败降级为 stats warning，不影响任务成败

## 5. 测试

- [x] 5.1 队列语义测试：入队即返回、串行排队、IndexJob 单一事实源（broker 不可用时状态查询正常）
- [x] 5.2 断点续跑测试：索引中途 kill worker，任务自动重投递续跑至 succeeded
- [x] 5.3 MinIO 降级测试：MinIO 不可达时索引仍 succeeded 且 stats 含 warning
- [x] 5.4 全量回归：既有 547 测试全绿

## 6. 部署与验收

- [x] 6.1 服务器拉起三个新容器 → 部署新 backend/worker → 触发真实索引验证全链路（入队、执行、SSE 进度、产物归档）
- [x] 6.2 破坏性验收：索引中途 docker restart worker，任务自动续跑至成功
- [x] 6.3 内存验收：docker stats 记录三容器常驻与索引高峰值，对照 design 实测账；server-notes 回填运维实况（含回滚方法）
