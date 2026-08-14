# Tasks: M10 首答提速

- [x] B1 GENERATE_MODEL 配置 + build_llm(for_generate) 分流；单测覆盖选择与回落
- [x] B2 上下文预算 fit_context_budget（裁 items 保前缀、min_items 底线、0=关闭）；单测覆盖边界与编号不变量
- [x] B3 报告 LLM 补 summary_model 回落（原先硬读 chat_model 会被问答选型带走）；单测
- [x] B4 rerank 超时 5s → 15s（实测长期静默降级）
- [x] B5 .env.example 补模型分工与预算说明段
- [x] V1 单测 553 全绿
- [x] V2 服务器实测：首 token 61.9s → 6.0-6.5s、完整回答 12.3s、[n] 引用对齐、模型路由核验
- [x] V3 提交（服务器先行上线，本次回填仓库）
