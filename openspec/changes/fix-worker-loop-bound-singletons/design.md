## Context

Celery worker 的 prefork 模型下，每个任务 `asyncio.run()` 起新循环。仓库里已经
有过一次同类事故并留下了解法（`celery_tasks.py` 模块注释第 2 点：任务 `finally`
里 `engine.dispose()` + `close_driver()`），但那份清单是**手工枚举**的，漏掉了
三个 LLM 单例。

## Goals / Non-Goals

**Goals**

- 三处单例跨事件循环复用不再抛错，`--max-tasks-per-child` 可以调回 8
- 修复对调用方透明：不要求任何人记得清理
- 回归测试能在修复前以**正确的原因**失败

**Non-Goals**

- 不改成功路径的任何可观察行为（并发上限、退避、超时）
- 不动 `celery_tasks.py` 已有的 DB/Neo4j 清理逻辑——它工作正常，本次不重构
- 不碰平台侧与 `deploy/`

## Decisions

### D1：资源自认循环，而非调用方清理

两种解法都能修好这个 bug：

| | 调用方清理（现有范式） | 资源自认循环（本次） |
|---|---|---|
| 位置 | `celery_tasks.py` 的 `finally` | 资源自身 |
| 新增单例时 | **要记得加进清理清单** | 自动正确 |
| 漏掉时 | 不报错，第二个任务才炸 | 不存在「漏掉」 |
| 覆盖范围 | 只有走 Celery 的路径 | Celery / FastAPI / 测试 |

选后者的决定性理由是**失效方向**：清理式解法漏一处就复发，而漏掉这件事本身
没有任何信号——这三个单例就是活证据。让资源自己负责，就没有可漏的清单。

这和平台侧「DB 失联降级为拒绝」「compose 基线零端口」是同一条取向：把默认状态
放在正确的一侧，而不是依赖每个使用者做对。

### D2：换循环时不关闭旧客户端

循环变化时旧 `AsyncOpenAI` 理应 `aclose()`，但那必须在**旧循环**里 await，而旧
循环此刻已经关了——跨循环调用只会抛新的错。所以直接丢弃引用：httpx 的 socket
随旧循环销毁而释放，代价是可能有 ResourceWarning，换来的是不引入一个「清理动作
自己会炸」的新故障点。

### D3：工厂传 lambda 而非绑定方法

`LoopLocal(self._make_client)` 在构造时就固定了绑定方法，之后替换类上的实现
（测试 monkeypatch、运行时换实现）不会生效——**而且失效是静默的**：工厂照常
返回旧实现的结果，测试却以为自己 patch 成功了。改成 `LoopLocal(lambda: self._make_client())`
每次调用时才查找。

这条是写测试时被抓出来的：第一版测试 monkeypatch `_make_client` 后断言调用次数为 0。

## Risks / Trade-offs

**R1：每次取值多一次 `get_running_loop()` 调用** → 可忽略。它是 C 实现的属性
读取，而调用点本身要发一次 LLM 网络请求。

**R2：Semaphore 的并发上限改为取值时读 settings**（原先在模块导入时读）→ 值不变，
只是读取时机后移。测试里 monkeypatch settings 后再调用，新实现会读到 patch 后的值——
这比旧行为更符合预期，不构成回归。

**R3：回归测试可能被后人「简化」成无竞争版本** → 缓解：测试文件头写明这个陷阱，
并留两条锚点测试——`test_bare_semaphore_still_breaks_across_loops` 钉住「有竞争
就会炸」这个前提，`test_single_acquire_does_not_reproduce` 钉住「无竞争测不出来」
这个反面。前者失败即意味着 Python 语义变了、该重新评估本方案是否还有必要。
