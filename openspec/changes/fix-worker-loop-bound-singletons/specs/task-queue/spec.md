## ADDED Requirements

### Requirement: 绑定事件循环的资源按循环持有
worker 每个任务以独立事件循环执行（`asyncio.run`）。凡绑定事件循环的进程级共享资源——asyncio 同步原语（Semaphore/Lock）、异步 HTTP 客户端的连接池、数据库与图数据库连接池——SHALL 按事件循环持有：检测到循环变化时重建，SHALL NOT 跨循环复用。同一 worker 进程连续执行多个任务 SHALL NOT 因此失败，因而 `--max-tasks-per-child` SHALL NOT 被用作规避该缺陷的手段。

新增此类共享资源时，正确性 SHALL 由资源自身保证，SHALL NOT 依赖调用方在任务结束时记得清理——清理清单漏项不会报错，只在下一个任务失败时才暴露。

#### Scenario: 同一 worker 进程连续执行两个索引任务
- **WHEN** 一个 worker 子进程完成索引任务后接着执行第二个任务
- **THEN** 第二个任务正常走完全部阶段，SHALL NOT 抛出 `is bound to a different event loop`

#### Scenario: 摘要阶段并发达到信号量上限
- **WHEN** 第二个任务的摘要阶段并发调用数超过 `summary_concurrency`、产生真实的信号量等待者
- **THEN** 等待与放行均在当前任务的事件循环内完成，任务成功结束

#### Scenario: 新增按循环持有的资源
- **WHEN** 引入新的进程级共享异步资源
- **THEN** 它自身在事件循环变化时重建，无需在任务收尾处登记清理
