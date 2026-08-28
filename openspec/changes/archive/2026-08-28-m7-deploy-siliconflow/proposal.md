# M7: 生产部署（硅基流动模型栈 + Rerank + 子路径上线）

## Why

系统六个里程碑后功能完备，一直跑在本机。用户要部署到自己的远程服务器：

1. 模型供应商统一切到硅基流动（SiliconFlow）——嵌入/对话/重排三类模型一个平台一个 key
2. 检索链路当前只有「向量多路召回 + RRF 融合」，没有精排——加 Rerank 提升问答命中质量
3. 服务器上已有一个 Docker Compose 项目在跑，Nginx 需要以**子路径**方式把流量导给本项目（用户已确认：子路径 + Docker Compose 形态）

## What Changes

| # | 变更 | 类型 |
|---|------|------|
| 1 | 模型栈切换：嵌入 `Qwen/Qwen3-Embedding-8B`（4096 维）、对话 `deepseek-ai/DeepSeek-V4-Flash`，均走 `https://api.siliconflow.cn/v1`（纯 env 配置，代码已兼容 OpenAI 端点） | 配置 |
| 2 | **Rerank 精排（新功能）**：`Qwen/Qwen3-Reranker-8B` 走 `/v1/rerank`（Cohere 风格接口，非 OpenAI 标准，需新客户端）；RRF 融合后精排，配置留空=关闭（向后兼容），失败降级 RRF 顺序 | 代码 |
| 3 | 子路径部署改造：Next.js `basePath` + 前端 API 地址相对化 + FastAPI `--root-path`（全部 env 驱动，默认空=现状不变） | 代码 |
| 4 | 部署件：`docker-compose.prod.yml`（端口收敛 127.0.0.1、restart、去 dev 卷）+ Nginx 子路径配置片段（**SSE 必须 `proxy_buffering off`**）+ `DEPLOY.md` 服务器步骤文档 | 新增 |

**API key 全部留占位符，用户自己填**（用户明确要求）。

## Capabilities

- `code-chat`（MODIFIED）：检索加 rerank 精排环节与降级场景
- `deployment`（ADDED）：生产部署形态——子路径反代、生产 compose、SSE 反代要求、MCP 远程接入安全项

## 不做什么

- 不做 CI/CD、HTTPS 证书自动化（服务器已有 Nginx 体系，证书沿用）
- 不做摘要/问答双档模型分离（可选省钱项，列 M8 候选）
- 不动 M4 路由探测器（monorepo 域名规整已在 M7 候选池，独立事项）

## 风险与迁移

- **嵌入维度 1024 → 4096**：`embed_key` 缓存键含 `model:dim`，天然隔离；服务器是全新库直接建 4096 索引。**本地若也切硅基流动**：lifespan 维度校验会拒启（旧 1024 索引 ≠ env 4096），需按 DEPLOY.md 附录删向量索引 + 全量重索引
- 硅基流动 `/v1/rerank` 响应格式按 Cohere 风格实现（`results[{index, relevance_score}]`），实测依赖用户 key——V 组验收含服务器实测步骤
- SSE 经 Nginx 默认缓冲会复现「一直思考中」事故（M6 血泪）——Nginx 片段强制 `proxy_buffering off`，验收必测流式
