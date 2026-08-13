# Tasks: M7 生产部署（B=后端 / F=前端 / D=部署件 / V=PM 验收）

## 1. 后端 B 组

- [x] B1 rerank 配置组：config.py 加 rerank_base_url / rerank_api_key / rerank_model（默认空=关闭）；.env.example 加硅基流动成套配置段（嵌入 Qwen/Qwen3-Embedding-8B 4096 维 + 对话 deepseek-ai/DeepSeek-V4-Flash + 重排 Qwen/Qwen3-Reranker-8B，key 全占位，注明 base_url 不带资源后缀、同一个 key 填三处）
- [x] B2 reranker 客户端（services/retrieval/reranker.py）：httpx POST `{base}/rerank`（Cohere 风格 body/响应）、超时 5s、文档截前 1500 字符；异常/超时/坏响应返回 None（由调用方降级）；单测覆盖正常重排/超时/坏 JSON/关闭态不发请求（httpx mock）
- [x] B3 search_layered 接入：RRF 后候选池扩为 top_k×3 → rerank 精排取 top_k → 图扩展（impact 模式不走）；rerank None 时保持 RRF 顺序 + warning；单测断言重排生效与降级路径
- [x] B4 子路径支持：backend Dockerfile CMD 加 `--root-path "${ROOT_PATH:-}"`；确认 MCP 挂载在剥前缀转发下正常（本地 curl 模拟验证）

## 2. 前端 F 组

- [x] F1 next.config.ts 加 basePath（NEXT_PUBLIC_BASE_PATH，默认空）；frontend Dockerfile 加 NEXT_PUBLIC_BASE_PATH / NEXT_PUBLIC_API_BASE 构建 args 并透传 compose；api.ts 确认相对路径 API_BASE 可用；`npm run build` 两种形态（空 / /rag）都通过

## 3. 部署件 D 组

- [x] D1 docker-compose.prod.yml：postgres/neo4j 无宿主端口映射；backend 绑 127.0.0.1:8001、frontend 绑 127.0.0.1:3300；restart: unless-stopped；无开发卷；frontend build args 注入 /rag 路径组
- [x] D2 deploy/nginx-rag.conf：`location /rag/api/` 剥前缀 → 127.0.0.1:8001（proxy_buffering off / proxy_cache off / proxy_read_timeout 3600s / http 1.1 + Connection ""）；`location /rag/` 不剥 → 127.0.0.1:3300；注释标明每行为什么存在（尤其 SSE 三件套）
- [x] D3 deploy/DEPLOY.md：服务器步骤（git clone → cp .env.example .env → 填 3 处硅基流动 key + SECRET_KEY + MCP_ALLOWED_HOSTS 加域名 → prod compose up --build → nginx include + reload → 验收清单五项）；MCP 远程接入段（含 MCP_AUTH_TOKEN 建议）；附录：本地切硅基流动的向量索引重建步骤（停后端 → Neo4j 删三个向量索引 → 改 .env → 起后端幂等重建 → 各项目 mode=full 重索引）

## 4. V 组（PM 验收）

- [x] V1 全量单测绿（含 reranker 新测试）+ 前后端 build 过 + 容器代码核验
- [x] V2 本地模拟子路径：临时 nginx 容器按 D2 片段跑通 `/rag/` 页面、`/rag/api/` 接口、SSE 聊天流式逐 token 到达；rerank 关闭态回归（现有行为不变）
- [ ] V3 服务器实测（用户填 key 后）：索引一个真实项目（4096 维索引建立）→ 聊天流式 → 后端日志确认 rerank 生效 → MCP 远程握手
- [x] V4 提交（含 tasks 勾选）；归档由用户触发
