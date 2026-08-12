# project-management — 深度参数与补跑入口（M5）

## MODIFIED Requirements

### Requirement: 触发索引任务
系统 SHALL 提供 `POST /projects/{id}/index` 触发索引，支持查询参数 `mode=auto|full`（默认 auto，语义见 indexing-pipeline「重建与增量语义」）与 `depth=deep|fast`（默认 deep，语义见 indexing-pipeline「索引深度模式」）；同一项目已存在 running 任务时 MUST 返回 409；任务创建后异步执行，接口立即返回任务 id，任务记录的 kind SHALL 反映实际执行模式（full/incremental），项目 SHALL 记录最近索引深度。

#### Scenario: 重复触发被拒绝
- **WHEN** 项目已有 running 索引任务，再次调用触发接口
- **THEN** 返回 409，且不创建新任务

#### Scenario: 失败后重试
- **WHEN** 项目上次索引任务为 failed，用户再次触发索引
- **THEN** 创建新任务并执行（auto 模式按增量判定规则决定实际路径）

#### Scenario: 强制全量
- **WHEN** 以 mode=full 触发索引
- **THEN** 执行全量重建，任务 kind 为 full

#### Scenario: 快速模式录入
- **WHEN** 以 depth=fast 触发索引
- **THEN** 任务按快速模式执行，项目最近索引深度记录为 fast

### Requirement: 项目详情页
前端 SHALL 提供项目详情页 `/projects/{id}`，含三页签：项目理解、功能地图（行为契约见 understanding-report 能力）、索引记录（历次任务列表：kind/status/stage/耗时/stats 展开/error_text）。项目列表卡片 SHALL 提供详情页入口；录入弹窗 SHALL 提供深度模式选择（默认深度，附一句成本提示）。fast 深度的项目详情页 SHALL 提供「生成深度理解」按钮（触发 depth=deep 的 auto 索引）。

#### Scenario: 查看索引记录
- **WHEN** 用户打开详情页「索引记录」页签
- **THEN** 按时间倒序看到历次任务的状态、阶段、耗时与统计，失败任务可见错误信息

#### Scenario: 快速项目升级深度
- **WHEN** 用户在 fast 项目详情页点击「生成深度理解」
- **THEN** 触发 depth=deep 的 auto 索引，完成后项目理解页签展示完整报告
