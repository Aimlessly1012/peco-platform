# indexing-pipeline — 索引管道（M1 精简版）

## ADDED Requirements

### Requirement: 仓库拉取
索引任务的 clone 阶段 SHALL 将仓库 clone 至 `data/repos/<project_id>/`（已存在则 fetch+reset 到目标分支最新），私有仓使用解密后的 token 组装认证 URL。拉取失败（认证/网络/仓库不存在）时任务 MUST 置为 failed 并记录可读的 error_text。任务成功结束时 SHALL 记录 `last_indexed_commit`。

#### Scenario: 私有仓 token 无效
- **WHEN** clone 阶段认证失败
- **THEN** 任务 failed，error_text 包含"认证失败"类提示，不泄露 token 内容

#### Scenario: 重复索引复用本地副本
- **WHEN** 项目已有本地副本时再次索引
- **THEN** 执行 fetch+reset 而非重新 clone

### Requirement: AST 分块
parse 阶段 SHALL 使用 tree-sitter 解析 python/javascript/typescript/tsx 文件（按扩展名路由），切块单位为顶层函数、类（超长类按方法二次切）、导出组件，模块级零散语句合并为一个 module-level 块。每块 MUST 记录 symbol、symbol_type、start_line、end_line、code、content_hash。单块超过约 1500 token 时二次切分并共享符号元数据。

#### Scenario: 解析 Python 文件
- **WHEN** 文件包含 2 个顶层函数和 1 个类（3 个方法，类整体未超限）
- **THEN** 产出 2 个 function 块 + 1 个 class 块，各带正确的行号范围与符号名

#### Scenario: 单文件解析失败不中断
- **WHEN** 某文件语法错误导致解析失败
- **THEN** 跳过该文件、stats.skipped 计数 +1，管道继续处理后续文件

### Requirement: 文件过滤规则
parse 阶段 SHALL 跳过：.gitignore 匹配项、内置忽略目录（node_modules/.git/dist/build/.next/__pycache__/venv 等）、二进制文件、单文件 >1MB、非支持扩展名文件；跳过数计入 stats。

#### Scenario: 忽略 node_modules
- **WHEN** 仓库包含 node_modules 目录
- **THEN** 其中文件不产生任何块，也不计入解析文件数

### Requirement: 嵌入向量化
embed 阶段 SHALL 调用 DashScope text-embedding-v3（OpenAI 兼容配置，模型与维度由环境变量控制）对块的嵌入文本批量向量化（批大小 10），并发受限且对限流/超时按指数退避重试。相同 `(project_id, content_hash)` 的块 SHALL 复用已有向量，不重复调用 API。

#### Scenario: 断点续跑不重复计费
- **WHEN** 上次任务在 embed 阶段中断后重新触发索引
- **THEN** 已嵌入过（content_hash 未变）的块直接复用向量，仅新块调用嵌入 API

#### Scenario: 限流退避
- **WHEN** 嵌入 API 返回限流错误
- **THEN** 按指数退避重试，最终失败则任务 failed 并记录 error_text

### Requirement: Neo4j 图写入
graph 阶段 SHALL 通过 Neo4jPropertyGraphStore 手动插入方式写入：`(:Project)`、`(:File {path, language, content_hash})`、`(:Chunk {symbol, symbol_type, code, context_text, start_line, end_line, embedding})` 节点及 `(Project)-[:HAS_FILE]->(File)`、`(File)-[:DEFINES]->(Chunk)` 边；所有节点 MUST 携带 project_id 属性实现项目隔离。后端启动时 SHALL 幂等创建 Chunk 向量索引（维度取 EMBEDDING_DIM），已存在但维度不符时 MUST 拒绝启动并给出重建指引。

#### Scenario: 写入后图结构可查
- **WHEN** 索引成功完成
- **THEN** Neo4j 中该 project_id 的 File/Chunk 节点数与 stats 一致，每个 Chunk 经 DEFINES 边可回溯到所属 File

#### Scenario: 向量索引维度冲突
- **WHEN** 启动时已存在维度 768 的 chunk 向量索引而 EMBEDDING_DIM=1024
- **THEN** 后端启动失败并提示维度冲突与重建方法

### Requirement: 全量重建语义（M1）
M1 的重新索引 SHALL 为全量重建：先删除 Neo4j 中该 project_id 的全部节点与边，再执行完整管道写入（嵌入层面仍可按 content_hash 复用向量缓存）。

#### Scenario: 重新索引后无残留
- **WHEN** 对已 ready 项目触发重新索引且源码有文件被删除
- **THEN** 完成后 Neo4j 中不存在已删除文件对应的 File/Chunk 节点

### Requirement: 任务阶段推进与统计
索引任务 SHALL 按 clone → parse → embed → graph 顺序推进并实时更新 stage/progress/stats；每阶段完成即持久化，任务成功后项目状态置 ready。

#### Scenario: 阶段推进可观测
- **WHEN** 任务从 parse 进入 embed
- **THEN** 任务记录的 stage 变为 embed，progress 相应推进
