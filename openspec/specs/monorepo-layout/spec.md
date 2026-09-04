# monorepo-layout Specification

## Purpose
TBD - created by archiving change merge-rag-backend. Update Purpose after archive.
## Requirements
### Requirement: RAG 后端与平台同仓且构建自足

RAG 后端 MUST 位于本仓库 `services/rag/`，其 Docker 构建上下文 MUST 自足——构建与运行
MUST NOT 引用 `../RAG_coder` 或仓库外的任何路径。

#### Scenario: 从新位置独立构建

- **WHEN** 在合并后的仓库执行 rag 服务的 `docker compose build`
- **THEN** 构建成功，构建上下文完全位于本仓库内

#### Scenario: 无外部仓库引用残留

- **WHEN** 全文搜索 `../RAG_coder`
- **THEN** 除历史性文档（openspec 归档、迁移记录）外无任何代码或配置命中

### Requirement: 数据卷跨迁移连续

编排配置 MUST 以卷级 `name:` 复用既有数据卷（`rag_coder_pgdata` / `rag_coder_neo4jdata` /
`rag_coder_miniodata` / `rag_coder_rabbitmqdata`），MUST NOT 因 compose 项目名变化创建新卷。
切换流程 MUST 在启动前后比对数据基线。

#### Scenario: 渲染检查在启动之前

- **WHEN** 执行 `docker compose config` 渲染合并后的编排
- **THEN** 四个卷渲染出的名字与既有卷名逐一相同

#### Scenario: 数据零丢失

- **WHEN** 从新仓库启动全栈并查询 `platform_users` 行数与 Neo4j 节点数
- **THEN** 与迁移前落盘的基线数字一致

### Requirement: 单一编排入口

`deploy/docker-compose.yml` MUST 是全栈唯一编排入口，平台服务 MUST 与 RAG 栈同属一个
compose 项目，MUST NOT 依赖 external network 缝合。

#### Scenario: 一条命令起全栈

- **WHEN** 执行 `docker compose up -d`
- **THEN** db、neo4j、rabbitmq、minio、backend、worker、platform 全部就绪，且平台容器能直连 backend

#### Scenario: external network 依赖消失

- **WHEN** 检查编排配置
- **THEN** 不存在 `external: true` 的网络声明

### Requirement: openspec 单仓

RAG 的全部 capability MUST 平移至根 `openspec/specs/`，未完结的 change MUST 随迁并可继续
推进。目录平移 MUST NOT 改写 capability 名或 spec 内容。

#### Scenario: 随迁 change 可继续

- **WHEN** 在合并后的仓库执行 `openspec list`
- **THEN** `m17-test-baseline` 出现在活跃 change 中，其 tasks 可照常勾选

#### Scenario: capability 完整平移

- **WHEN** 列出根 `openspec/specs/`
- **THEN** RAG 的 8 个 capability 目录全部存在且内容逐字节与源一致

### Requirement: 迁移前后运行时行为不变

本次迁移 MUST NOT 改变任何 API 行为、鉴权语义或路由；`/rag/api/*` 与 MCP 端点的对外
表现 MUST 与迁移前一致。

#### Scenario: 测试套件作为行为基线

- **WHEN** 在 `services/rag` 下运行迁移前全绿的 pytest 套件
- **THEN** 全绿，零跳过新增

#### Scenario: 端到端链路冒烟

- **WHEN** 登录后走一轮 项目列表 → 详情 → chat 提问
- **THEN** SSE 流式回答正常到达，引用联动正常

### Requirement: CI 随迁并按路径触发

RAG 的 CI MUST 在本仓库生效，`services/rag/**` 的改动 MUST 触发其测试 job；
与 rag 无关的改动 MUST NOT 触发。

#### Scenario: 路径过滤生效

- **WHEN** 一次仅改动 `app/front/**` 的提交推送
- **THEN** rag 测试 job 不运行

#### Scenario: rag 改动触发

- **WHEN** 一次改动 `services/rag/**` 的提交推送
- **THEN** rag 测试 job 运行并通过

