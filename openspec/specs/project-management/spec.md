# project-management Specification

## Purpose
项目管理能力：录入 Git 仓库项目、展示项目列表与索引状态、触发与查询索引任务、删除项目，以及进程重启后的任务恢复语义。

## Requirements

### Requirement: 录入 Git 仓库项目
系统 SHALL 提供录入接口：接收仓库名称、git url（GitHub/GitLab，https）、可选访问 token、可选分支（默认 default branch），创建项目记录，初始状态为 `pending`。token MUST 使用 Fernet 加密后存储（`git_token_encrypted`），且 MUST NOT 出现在任何 API 响应或日志中。

#### Scenario: 成功录入私有仓库
- **WHEN** 用户提交名称、私有仓 git url、有效 token
- **THEN** 创建项目记录，状态 `pending`，返回项目 id；数据库中 token 为密文

#### Scenario: 录入后 API 不回显 token
- **WHEN** 任何项目查询接口返回项目数据
- **THEN** 响应中不包含 token 明文或密文字段

### Requirement: 项目列表与状态展示
系统 SHALL 提供项目列表接口，返回每个项目的名称、git url、状态（pending/indexing/ready/failed）、最后索引 commit、最后索引时间；前端项目列表页 SHALL 以状态徽章展示，索引中的项目 SHALL 展示当前阶段与进度百分比。

#### Scenario: 查看索引中的项目
- **WHEN** 某项目存在 running 状态的索引任务（如 stage=embed, progress=60）
- **THEN** 列表接口/页面显示该项目状态为 indexing，并能看到阶段 embed 与进度 60%

### Requirement: 触发索引任务
系统 SHALL 提供 `POST /projects/{id}/index` 触发索引；同一项目已存在 running 任务时 MUST 返回 409；任务创建后异步执行，接口立即返回任务 id。

#### Scenario: 重复触发被拒绝
- **WHEN** 项目已有 running 索引任务，再次调用触发接口
- **THEN** 返回 409，且不创建新任务

#### Scenario: 失败后重试
- **WHEN** 项目上次索引任务为 failed，用户再次触发索引
- **THEN** 创建新任务并执行（M1 语义为全量重建）

### Requirement: 索引任务进度查询
系统 SHALL 提供任务查询接口，返回任务的 kind、status、stage（clone/parse/embed/graph）、progress(0-100)、stats（文件数/块数/跳过数）、error_text；前端 SHALL 以轮询（约 2s）刷新进度。

#### Scenario: 查询运行中任务
- **WHEN** 查询 running 任务
- **THEN** 返回当前 stage 与 progress，stats 随处理推进更新

#### Scenario: 查询失败任务
- **WHEN** 查询 failed 任务
- **THEN** 返回 error_text 供前端展示失败原因

### Requirement: 删除项目
系统 SHALL 支持删除项目：删除 Postgres 中项目及关联记录（任务、会话、消息）、Neo4j 中该 project_id 的全部节点与边、本地仓库副本目录。前端删除操作 MUST 二次确认。

#### Scenario: 删除已索引项目
- **WHEN** 用户确认删除一个 ready 状态项目
- **THEN** 项目记录、Neo4j 子图（该 project_id 的所有节点）、`data/repos/<project_id>/` 目录均被删除

### Requirement: 进程重启后的任务恢复语义
后端启动时 SHALL 将所有 running 状态的索引任务标记为 failed（error_text 注明 stale），对应项目状态回退为 failed，允许用户重新触发。

#### Scenario: 索引中重启后端
- **WHEN** 索引任务 running 时后端进程重启
- **THEN** 启动后该任务为 failed（stale），项目可重新触发索引
