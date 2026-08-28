## ADDED Requirements

### Requirement: 检索实现基于框架组件
检索链 SHALL 基于 LangChain 1.x 组件实现（向量层 Neo4jVector + Embeddings 协议 + 组件化 rerank），SHALL NOT 以手写 driver 调用作为向量检索入口；图扩展等无框架 API 的定制查询 SHALL 收敛在框架提供的定制插槽或明确标注的外挂查询函数中。重构 SHALL 保持既有检索行为与引用契约不变。

#### Scenario: 引用契约不因重构变化
- **WHEN** 对同一项目提出与重构前相同的问题
- **THEN** citations 的字段结构（路径/行号/模块/via/score）与 SSE 事件契约与重构前一致

#### Scenario: 组件可替换
- **WHEN** 更换嵌入模型或 rerank 服务配置
- **THEN** 仅配置层变更即可生效，检索链代码不需要修改
