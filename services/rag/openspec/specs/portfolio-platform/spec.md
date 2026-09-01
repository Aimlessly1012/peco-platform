# 作品集平台

peco-platform：统一入口、作品集首页与组件库展示（M12）。

### Requirement: 平台路由与首页
系统 SHALL 提供一个 Next.js 单体前端占据站点根路径，含：作品集首页（`/`）、登录页
（`/login`）、待审核页（`/pending`）、组件库展示（`/front`）、RAG Coder 页面
（`/rag/*`）、管理后台（`/admin`）。全站 SHALL 使用同一套终端风设计令牌，`/front`
的 antd 组件经 ConfigProvider 适配该令牌。

#### Scenario: 访客浏览作品集
- **WHEN** 未登录访客访问根路径
- **THEN** 看到作品集首页与各作品入口，视觉风格全站一致

#### Scenario: 组件库可交互演示
- **WHEN** 访问 `/front`
- **THEN** 看到 heitu 组件库的文档与可交互 demo（FormRender、charts 等），
  其视觉与站点其余部分同源（无 antd 默认风格割裂）

### Requirement: RAG Coder 页面迁入
RAG Coder 的全部前端页面（项目列表、项目详情三页签、聊天、MCP 接入说明、用户管理）
SHALL 迁入平台的 `/rag/*` 路由，交互与功能保持与迁移前一致；RAG 独立前端容器 SHALL 下线。
页面 SHALL 通过 `/rag/api/*` 访问后端，SSE 流式（聊天、索引进度）与引用联动行为不变。

#### Scenario: 迁移后功能无回归
- **WHEN** 已批准用户在 `/rag` 下录入项目、查看报告、发起聊天
- **THEN** 索引进度实时推送、报告各图渲染、答案流式输出与 `[n]` 引用联动均与迁移前一致
