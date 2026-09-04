## 1. 定位与复现

- [x] 1.1 确认根因：三个模块级单例的 `asyncio.Semaphore` 与 `AsyncOpenAI` 绑定首次使用的事件循环
- [x] 1.2 稳定复现——**并发数必须超过信号量上限**才会绑定循环；单次 acquire 复现不出来，排查时先写的那版脚本因此误判为「无法复现」
- [x] 1.3 三处逐一验证均可复现（summarizer / embedder / report_llm）

## 2. 实现

- [x] 2.1 新增 `app/core/loop_local.py`：`LoopLocal[T]`，惰性创建 + 循环变化时重建 + `reset()`
- [x] 2.2 三处单例的 `_semaphore` 与 `client` 改由 `LoopLocal` 持有，调用点写法（`async with self._semaphore` / `await self.client.xxx`）保持不变
- [x] 2.3 工厂传 lambda 而非绑定方法（D3）——否则 monkeypatch 静默失效

## 3. 回归测试

- [x] 3.1 `tests/test_loop_bound_singletons.py`：三个单例各一条「连续两个事件循环」的回归，全部制造真实竞争
- [x] 3.2 `LoopLocal` 自身四条：同循环内复用、换循环重建、`reset` 生效、falsy 值也缓存
- [x] 3.3 两条锚点：裸 Semaphore 跨循环确实会炸（前提成立性）、单次 acquire 复现不出来（陷阱记录）
- [x] 3.4 **验证测试有效性**：还原到修复前的源码跑同一批测试，确认它们以 `RuntimeError: is bound to a different event loop` 失败——而非因 mock 不到属性而 AttributeError。第一版测试 patch 的是新实现才有的 `_make_client`，在旧代码上只会 AttributeError，证明不了任何事，已改为 patch 两版都有的 `client` property

## 4. 验收

- [x] 4.1 `uv run pytest -m "not integration"` 全绿：708 passed, 2 skipped
- [x] 4.2 覆盖率 79.23%，高于门槛 78%（修复前 78.68%）
- [x] 4.3 成功路径行为未变：并发上限、退避重试、超时均保持原值
- [x] 4.4 改动范围只在 `services/rag/`，未碰平台侧与 `deploy/`

> 2 skipped 是 `.env` 隔离护栏——仓库根没有 `.env` 时它按设计跳过，CI 会造一份含假 key 的
> `.env` 所以那边真实执行。这不是本次引入的。
