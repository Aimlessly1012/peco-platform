# Proposal: M6 需求功能思维导图（XMind 式）

## Why

用户反馈现有思维导图两个根本问题：①样式——mermaid mindmap 是径向泡泡布局，与 XMind 式横向逻辑图（左根右枝、可折叠、可缩放）体验差距大；②视角——现图内容是"模块名 + 文件数"的**代码结构**，而用户从 M1 起要的就是**需求功能**导图（产品有什么功能、功能域下有哪些功能点，用业务语言表达）。这是"通过代码理解项目"核心诉求的最后一块拼图。

## What Changes

- **功能导图生成**（替代现顶层结构导图成为报告主导图）：三层结构 `产品定位 → 功能域 → 功能点`。功能域 = 模块业务名；功能点由**每模块一次 flash 小调用**提取（输入该模块 L3 业务目标/关键流程 + 路由清单，输出 2-6 条中文功能点短语），程序化拼装为 **Markdown 层级文本**（markmap 原生输入，无语法校验负担）。按模块 agg_hash 缓存；单模块提取失败降级为路由段清单；fast 模式纯程序化（模块业务名 + 路由段）
- **前端 markmap 渲染**：新增 markmap 组件（横向逻辑图、节点折叠/展开、缩放平移——XMind 式交互），项目理解页签主导图换用之；markdown 源码一键复制（可直接粘贴进 XMind/Obsidian 使用）
- **结构视角保留不丢**：原模块结构导图（Project→Module）与文件子导图移入「功能地图」页签（技术视角归技术页签），报告页签专注需求视角
- 报告存储：understanding_reports 新增 feature_map_markdown 列；旧报告该字段为空时前端回退展示原 mindmap_mermaid

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `understanding-report`: 「报告三件套生成」的导图件改为功能导图（Markdown 层级 + 生成策略 + 缓存 + 降级）；「报告与模块地图查询 API」增加 feature_map_markdown 字段；「前端项目理解展示」主导图改 markmap 渲染与折叠交互，结构导图移至功能地图页签

## Impact

- 代码：`services/report/`（功能点提取器 + markdown 拼装）、alembic 0004（feature_map_markdown 列）、前端 markmap-lib/markmap-view 依赖与组件、项目理解/功能地图两页签调整
- 成本：deep 模式每项目新增 ≈ 模块数次 flash 小调用（49 模块 ≈ 49 次短调用，agg_hash 缓存后重索引近零）；fast 模式零新增
- 兼容：旧报告无 feature_map 时回退旧导图展示；无破坏性变更
