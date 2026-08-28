# M7 设计

## D1 模型栈切换（纯配置）

三组 env，全走硅基流动（`.env.example` 加成套注释段，key 占位）：

```env
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1     # SDK 自动拼 /embeddings
EMBEDDING_API_KEY=your-siliconflow-key
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
EMBEDDING_DIM=4096

CHAT_BASE_URL=https://api.siliconflow.cn/v1
CHAT_API_KEY=your-siliconflow-key
CHAT_MODEL=deepseek-ai/DeepSeek-V4-Flash

RERANK_BASE_URL=https://api.siliconflow.cn/v1        # 客户端拼 /rerank
RERANK_API_KEY=your-siliconflow-key
RERANK_MODEL=Qwen/Qwen3-Reranker-8B
```

决策：
- **维度取 4096（模型原生）**。Qwen3-Embedding-8B 支持 MRL 降维，但服务器是全新库，原生维度质量最优；个人自用规模 Neo4j 内存可承受。`embed_key = hash(model:dim:text)` 使新旧缓存天然隔离。
- 嵌入/对话代码零改动（现有 OpenAI 兼容客户端 + env 三元组已就绪）。
- base_url 统一**不带资源后缀**（`/v1`），嵌入由 OpenAI SDK 拼 `/embeddings`，rerank 由新客户端拼 `/rerank`——与用户给的完整 URL 语义一致，.env.example 注释说明。

## D2 Rerank 精排链路

**位置**：`search_layered` 内，RRF 融合之后、图扩展一跳之前：

```
向量多路召回（over-fetch 4x，已有）
  → RRF 融合 → 候选池 top (top_k × 3)
  → [rerank 开启] /v1/rerank 精排 → 取 top_k     ← 新增
  → 图扩展一跳（CALLS_API / IMPORTS 邻居，via_edge 标记）
```

理由：rerank 只衡量「query ↔ 文本」相关性；图扩展带出的邻居是**结构关联**（调用方/被调方），不该被文本相关性挤掉，故 rerank 在图扩展之前收敛主候选。

**客户端**（`services/retrieval/reranker.py`，httpx 直调，Cohere 风格）：

```
POST {RERANK_BASE_URL}/rerank
{"model": ..., "query": ..., "documents": [文本...], "top_n": k}
→ {"results": [{"index": i, "relevance_score": s}, ...]}
```

- 文档文本：chunk 用代码文本、摘要节点用摘要文本，每篇截前 1500 字符（8B 重排模型上下文有限，且长文不增益）
- **开关语义**：`RERANK_API_KEY` 或 `RERANK_BASE_URL` 为空 = 关闭（现状行为，全部现有测试不受影响）
- **降级**：调用异常/超时（5s）/结果解析失败 → warning 日志 + 保持 RRF 顺序返回，绝不阻塞问答
- impact 模式（影响面分析）不走 rerank——它的排序语义是图距离不是文本相关性

## D3 子路径部署改造（env 驱动，默认空 = 现状）

约定子路径为 `/rag`（Nginx 片段与文档统一用它，用户可全局替换）：

| 层 | 改动 | 生产值 |
|----|------|--------|
| Next.js | `next.config.ts` 加 `basePath: process.env.NEXT_PUBLIC_BASE_PATH \|\| ""`；frontend Dockerfile 加 build args（NEXT_PUBLIC_* 是构建期变量） | `/rag` |
| 前端 API | `NEXT_PUBLIC_API_BASE` 支持相对路径 | `/rag/api`（同域，浏览器直打） |
| FastAPI | Dockerfile CMD 加 `--root-path "${ROOT_PATH:-}"`（只影响 openapi.json 地址生成，路由本身不加前缀） | `/rag/api` |
| Nginx | `location /rag/api/` 剥前缀转发 backend:8000；`location /rag/` 不剥转发 frontend:3000（Next 自己处理 basePath） | — |

**SSE 反代硬要求**（M6「一直思考中」事故的 Nginx 版预防）：

```nginx
location /rag/api/ {
    proxy_buffering off;          # SSE 逐事件透传，缺这行聊天流式必挂
    proxy_cache off;
    proxy_read_timeout 3600s;     # 索引任务轮询 + 长回答
    proxy_http_version 1.1;
    proxy_set_header Connection "";
}
```

**MCP 远程接入安全**（DEPLOY.md 必写）：`MCP_ALLOWED_HOSTS` 默认白名单只有 localhost——服务器部署必须加自己的域名，否则 DNS 重绑定防护会拦掉所有远程 MCP 请求；公网暴露时强烈建议同时配 `MCP_AUTH_TOKEN`。

## D4 生产 Compose 与部署文档

`docker-compose.prod.yml`（独立文件，不动开发版）：
- postgres/neo4j **不映射宿主端口**（仅 compose 网络内互通；neo4j browser 需要时临时 `-p 127.0.0.1:7474:7474`）
- backend/frontend 只绑 `127.0.0.1:8001` / `127.0.0.1:3300`（流量全走 Nginx；3300 避开已有项目常用 3000）
- `restart: unless-stopped`；去掉开发卷挂载，镜像内代码为准
- frontend 构建注入 `NEXT_PUBLIC_BASE_PATH=/rag`、`NEXT_PUBLIC_API_BASE=/rag/api`

`deploy/DEPLOY.md` 步骤骨架：clone → `.env` 填 3 个 key（硅基流动同一个 key 填三处）→ `docker compose -f docker-compose.prod.yml up -d --build` → 把 `deploy/nginx-rag.conf` include 进已有 server 块 → `nginx -s reload` → 验收清单（首页/建项目/索引/聊天流式/MCP）。附录：本地切硅基流动的向量索引重建步骤。

## D5 验收口径

- 单测：reranker 客户端（httpx mock：正常/超时/坏响应/关闭态）+ search_layered 接入（rerank 重排生效、失败降级 RRF）
- 本地模拟：`NEXT_PUBLIC_BASE_PATH=/rag` 本地 build + 临时 nginx 容器验证子路径全链路（页面资源、API、SSE 流式）
- 服务器实测（用户填 key 后）：索引真实项目 → 聊天流式无缓冲卡顿 → rerank 日志生效 → MCP 远程握手
