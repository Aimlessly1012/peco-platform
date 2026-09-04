# 修 worker 的模块级单例跨事件循环复用

## 现象

统一栈 peco 上线后（2026-09-03），同一个 Celery 子进程跑**第二个**索引任务时
`stage=summarize` 必炸：

```
RuntimeError: <asyncio.locks.Semaphore ... [locked]> is bound to a different event loop
```

首个任务永远正常，换任务才炸——所以 `--max-tasks-per-child=1` 能止血
（每个任务换一个子进程，等于每个进程只用一个循环）。代价是每个任务多一次
进程启动与模块导入。

## 根因

三个模块级单例在 `__init__` 里建 `asyncio.Semaphore`、并缓存 `AsyncOpenAI`：

| 单例 | 文件 |
|---|---|
| `summarizer` | `services/rag/app/services/ingest/summarizer.py` |
| `embedder` | `services/rag/app/services/ingest/embedder.py` |
| `report_llm` | `services/rag/app/services/report/llm.py` |

而 `celery_tasks.py` 每个任务 `asyncio.run(...)` 起一个全新循环。asyncio 的同步
原语与 httpx 连接池都绑定首次使用时的循环，跨任务复用即失效。

`celery_tasks.py` 的模块注释里已经为 DB 引擎池与 Neo4j driver 处理过同一类问题
（任务 `finally` 里 dispose），但那份清单漏了这三处。

### 一个定位时才发现的条件：必须有竞争

**Semaphore 只在产生真正的等待者时才绑定循环。** 单次 `async with sem` 不会绑，
所以「连续两次 `asyncio.run` 各 acquire 一次」这种复现脚本**跑不出问题**——
排查时先写的就是这样一条，一度误判为无法复现。并发数必须超过信号量上限。

这条对回归测试是决定性的：不制造竞争的测试在修复前也是绿的，等于没写。

## 方案

新增 `app/core/loop_local.py` 提供 `LoopLocal[T]`——惰性创建、并在事件循环变化时
重建的资源持有者。三个单例的 Semaphore 与客户端都改由它持有。

**为什么不沿用 `celery_tasks` 的清理式解法**：那种做法要求每个调用方记得在
`finally` 里清理，本次这三处就是漏掉的证据，而且漏掉时不报错、只在第二个任务才炸。
改成资源自己认循环后，Celery、FastAPI、测试三条路径同样受益，不依赖任何人记得。

## 影响

- 成功路径行为不变：并发上限、退避重试、超时全部保持原值
- 仅 `services/rag/`，不碰平台侧，不改 `deploy/`
- `--max-tasks-per-child` 是否从 1 改回 8，由架构会话在部署后决定
