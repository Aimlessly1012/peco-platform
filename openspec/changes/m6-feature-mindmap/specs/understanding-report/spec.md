# understanding-report — 需求功能思维导图（M6）

## MODIFIED Requirements

### Requirement: 报告三件套生成
索引管道 SHALL 在 report 阶段（graph 之后）为项目生成并持久化理解报告：①需求逻辑文档（Markdown，map-reduce 分批生成：模块按 kind 分组、每批 ≤10 个模块的 L3 摘要并发生成章节，最后以章节清单 + 路由地图生成系统概述）；②**需求功能思维导图**（Markdown 层级文本，三层：产品定位 → 功能域 → 功能点。功能域取 kind 为 page/api 模块的业务名（shared 不入图）；功能点由每模块一次 LLM 小调用提取（输入模块 L3 与路由清单 ≤15 条，输出 2-6 条 ≤14 字中文动宾短语），按模块 agg_hash 缓存，单模块失败降级为路由段清单，fast 模式全程序化）；③模块结构导图（Mermaid mindmap，仅 Project→Module 两层，程序化生成，供功能地图页签使用）；④**业务流程图**（每条 L4 核心业务流一张 Mermaid flowchart，2-4 张：节点为用户动作/系统行为的业务步骤 ≤8 个、文案 ≤12 字、禁文件名与函数名；经启发式校验、失败重试 1 次、再失败以业务流原文为 fallback_text；fast 模式跳过）；⑤模块数据流图（Mermaid flowchart，模块间聚合边，程序化生成，供功能地图页签使用）；⑥核心流程时序图（对 kind 为 api/page 且文件数 ≥2 的模块最多 6 个，输入瘦身：模块 L3 + 入口 L2 ≤5 个 + 入口相关边各 ≤15 条）。报告 SHALL 按 project_id 覆盖写。

#### Scenario: 索引完成自动产出报告
- **WHEN** 一个全栈项目索引任务成功完成（deep 模式）
- **THEN** understanding_reports 中存在该项目记录，含非空 doc_markdown、feature_map_markdown、mindmap_mermaid、dataflow_mermaid 与至少一张模块时序图

#### Scenario: 功能导图为业务语言
- **WHEN** 查看 deep 模式生成的 feature_map_markdown
- **THEN** 功能域为模块业务名、功能点为中文动宾短语（非文件名/技术词），且每个功能域对应图中真实存在的 page/api 模块

#### Scenario: 多功能域项目逐层归组
- **WHEN** 功能域超过 8 个的项目生成功能导图
- **THEN** 导图为四层（产品 → 业务组 → 功能域 → 功能点），业务组为中文业务词且成员均为真实功能域，无遗漏（未归组者入「其他」）；归组失败时降级为三层平铺

#### Scenario: 页面结构导图程序化生成
- **WHEN** deep 或 fast 索引完成
- **THEN** page_map_markdown 按页面路由 path 层级组织（产品 → 一级路由段 → 页面 → 逻辑要点），页面与路由段均来自真实路由数据

#### Scenario: 单模块提取失败不塌整图
- **WHEN** 某模块功能点提取两次调用失败
- **THEN** 该功能域降级为路由段清单，其余功能域正常，任务标 partial

#### Scenario: 业务流程图为业务步骤
- **WHEN** 查看 deep 模式生成的业务流程图源码
- **THEN** 每张对应一条 L4 核心业务流，节点为业务动作描述，不含文件名或函数名

#### Scenario: 数据流图与图数据一致
- **WHEN** 查看 dataflow_mermaid 源码
- **THEN** 其中每条边对应 Neo4j 中真实存在的模块间 CALLS_API 或 IMPORTS 聚合关系，不含图中不存在的模块

### Requirement: 报告与模块地图查询 API
系统 SHALL 提供 `GET /projects/{id}/report`（返回报告：doc_markdown、**feature_map_markdown**、**business_flows**（[{title, mermaid, fallback_text}]）、mindmap_mermaid、dataflow_mermaid、sequences，以及 depth 标记；无报告时 404 并附提示语）与 `GET /projects/{id}/modules`（返回模块列表：name/kind/route_prefix/summary 及各模块文件清单与 L2 摘要，数据实时读 Neo4j）。旧报告缺失的字段（dataflow_mermaid、feature_map_markdown）可为空，客户端 SHALL 兼容。

#### Scenario: 旧项目无报告
- **WHEN** 项目最后一次索引早于 report 功能上线，查询报告
- **THEN** 返回 404 与"请重新索引以生成报告"类提示

### Requirement: 前端项目理解展示
项目详情页「项目理解」页签 SHALL 为**纯需求视角**：markmap 渲染需求功能思维导图为主导图（横向逻辑图：节点折叠/展开、缩放平移，初始展开至功能域层；提供展开全部/收起/源码复制——markdown 源码可直接粘贴进 XMind；渲染异常回退显示 markdown 文本，不得白屏；feature_map 为空的旧报告回退渲染 mindmap_mermaid 并提示重新索引）+ **业务流程图**（business_flows 逐张渲染，失败显示 fallback_text；为空时隐藏该区块）+ 需求文档 + 各模块时序图。**代码视角图全部归「功能地图」页签**：模块结构导图、文件子导图与模块数据流图。fast 模式产物 SHALL 显示"快速模式"标识与「生成深度理解」引导。

#### Scenario: XMind 式交互
- **WHEN** 用户打开 deep 报告的项目理解页签
- **THEN** 功能导图以横向逻辑图渲染，初始展开到功能域层，点击功能域可展开/收起其功能点，可复制 markdown 源码

#### Scenario: 旧报告回退
- **WHEN** 项目报告无 feature_map_markdown
- **THEN** 主导图位置渲染旧 mindmap_mermaid 并提示"重新索引获取功能导图"，页面其余正常
