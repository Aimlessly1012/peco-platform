# regression-testing Specification

## Purpose
回归测试基线能力：以 CI 双档（单测档 / 集成档）门禁、覆盖率基线防跌、测试环境安全护栏（不加载真实 .env、单测禁外网、集成依赖不可达即 skip）与用例超时、共享夹具收敛约束，保证每次提交的回归可见且可复现（M17）。

## Requirements

### Requirement: CI 回归门禁
仓库 SHALL 配置 CI 工作流：每次 push 与 PR SHALL 自动运行单测档（`-m "not integration"`，不依赖任何外部服务）；集成档（`-m integration`，起 Neo4j 与 MinIO 服务容器）SHALL 在 CI 中可运行并在 main 分支 push 时执行。两档任一失败 SHALL 以红灯呈现。

#### Scenario: PR 单测红灯可见
- **WHEN** 一次提交破坏了任一单测用例并推送
- **THEN** CI 单测档失败，提交/PR 上呈现红灯与失败用例名

#### Scenario: 集成档在 CI 内自带服务跑通
- **WHEN** CI 集成档执行
- **THEN** Neo4j 与 MinIO 由工作流自行拉起并通过健康检查，集成用例全部执行，不依赖任何外部环境

### Requirement: 覆盖率基线与防跌
单测档 SHALL 产出覆盖率报告；仓库 SHALL 记录覆盖率基线值（`fail_under`，取首次实测向下取整），覆盖率低于基线时 CI SHALL 失败。基线值上调 SHALL 是显式修改。

#### Scenario: 覆盖率跌破基线被拦截
- **WHEN** 新增大量无测试代码使覆盖率低于基线值
- **THEN** CI 单测档失败并报告当前值与基线值

### Requirement: 测试环境安全护栏
测试运行 SHALL NOT 加载仓库内任何真实 `.env`（conftest 强制以无 env 文件方式重建配置并注入哑凭据），单测档 SHALL 禁止对外网络访问（允许 localhost）；无论从哪个工作目录启动测试，上述护栏 SHALL 一致生效。集成用例在依赖服务不可达时 SHALL skip 并说明原因，SHALL NOT 以连接异常形式失败。

#### Scenario: 从仓库根误跑不打真实 API
- **WHEN** 在仓库根目录（存在含真实 key 的 `.env`）直接运行 pytest
- **THEN** 配置为哑凭据，任何对外 API 调用被拒绝，测试结果与从 backend/ 目录运行一致

#### Scenario: Neo4j 未启动时集成用例跳过
- **WHEN** 本地未启动 Neo4j 而运行 `-m integration`
- **THEN** 集成用例被标记 skipped 并附「Neo4j 不可达」原因，退出码不为失败

### Requirement: 测试超时与夹具收敛
所有用例 SHALL 有超时上限（全局默认，集成 marker 可放宽），挂死用例被中断而非阻塞整轮；跨文件共享的测试夹具（FakeLLM、make_tree 等）SHALL 收敛于 `tests/helpers` 或 conftest，测试文件之间 SHALL NOT 相互 import。

#### Scenario: 挂死用例被超时中断
- **WHEN** 某异步用例意外永久等待
- **THEN** 该用例在超时上限处失败并给出堆栈，其余用例继续执行

#### Scenario: 共享夹具重构不跨文件断链
- **WHEN** 重构 test_report.py 的内部实现
- **THEN** 其他测试文件不受影响（不存在对它的 import）
