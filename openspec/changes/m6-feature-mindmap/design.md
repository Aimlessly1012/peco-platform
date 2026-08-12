# Design: M6 需求功能思维导图

## Context

M5 后报告四件俱全但主导图仍是代码结构视角（模块+文件数），且 mermaid mindmap 的径向布局与用户期望的 XMind 式体验不符。既有可复用件：L3 模块摘要（业务目标/关键流程）、模块 agg_hash 缓存机制、报告 map-reduce 基建、MermaidDiagram 组件模式、fast/deep 双模式。

## Goals / Non-Goals

**Goals:**

- 报告主导图变为需求功能视角：`产品定位 → 功能域 → 功能点`，全中文业务语言
- 前端 XMind 式交互：横向逻辑图、折叠/展开、缩放；49 功能域大项目默认收起到功能域层仍可读
- 功能点提取可缓存、可降级、fast 零 LLM；markdown 源码可直接复制进 XMind

**Non-Goals:**

- 导图人工编辑/回写；功能点与代码的双向跳转（后续可做：功能点挂模块锚点即可扩展）
- 替换功能地图页签的结构树（结构视角保留原位）

## Decisions

### D1: 功能点提取 = 每模块独立小调用（非整树一次生成）

单模块 prompt：输入 = 模块业务名 + L3（业务目标/关键流程）+ 该模块路由清单（page 的页面路径 / api 的端点，≤15 条），输出 = 2-6 条功能点短语（每条 ≤14 字，动宾结构，禁止技术词如"组件/接口/文件"）。理由：输入小（≤1.5k token）不塌方；按模块 agg_hash 缓存（复用 L3 缓存键体系）；单模块失败只降级该功能域（列路由段），零整树风险；shared/dir 类模块跳过提取（直接列名或省略——shared 不是用户功能）。

### D2: 产物 = Markdown 层级文本（feature_map_markdown）

```markdown
# <项目名>：<L4 项目定位一句>
## 推广管理
- 创建广告任务
- 保存/编辑草稿
- 按模板批量创建
## 素材中心
- 素材任务台账
...
```

markmap 原生吃 markdown，无语法校验负担（对比 mermaid 时序图的校验-重试-降级链路，这条管线"必然成功"）。存 understanding_reports.feature_map_markdown（alembic 0004）。fast 模式程序化版：功能点行 = 路由段清单。

### D3: 前端 markmap 组件与页签分工

- 新增 `MarkmapView` 组件：markmap-lib（transform）+ markmap-view（渲染），动态 import 关 SSR，初始展开到功能域层（depth 2），提供展开全部/收起/适应窗口按钮与源码复制；渲染异常回退显示 markdown 文本（不白屏）
- 项目理解页签主导图 = MarkmapView(feature_map_markdown)；feature_map 为空（旧报告）回退渲染 mindmap_mermaid
- 结构导图（Project→Module mermaid）与模块文件子导图移入功能地图页签顶部——技术视角归技术页签
- markmap-lib/markmap-view 为新增依赖（体积可接受，动态加载）

### D4: 与 kind 的映射规则

功能域仅取 kind=page 与 kind=api 的模块（用户可感知功能）；page 与 api 模块业务名相同/相近时不合并（保持"前台功能/服务能力"并列，名称冲突加 kind 后缀）；dir 降级模块以目录名做功能域、功能点为路由段或文件名段（fast 同此）；shared 模块不入功能导图。

## Risks / Trade-offs

- [LLM 功能点幻觉] → 输入含真实路由清单锚定 + 输出条数上限 + prompt 禁编造"清单外能力"；抽查验收
- [49 次小调用增加 deep 成本] → 单次 ≤1.5k token 输入 / ~60 token 输出，全量 ≈ 8 万 token（¥0.1 级）；agg_hash 缓存后重索引零成本
- [markmap 与终端风视觉冲突] → 组件容器沿用设计令牌（线框/无圆角外壳），markmap 内部配色用 CSS 变量收敛到 accent/ink 系
- [旧报告无 feature_map] → 前端回退旧导图 + 「重新索引获取功能导图」提示

## Migration Plan

alembic 0004 加列（nullable）。旧项目重索引即得功能导图；不重索引则回退展示。

## Open Questions

（无）
