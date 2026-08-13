# 生产部署（Nginx 子路径 /rag）

面向：服务器上已经跑着别的 Docker Compose 项目，RAG Coder 挂在同一域名的 `/rag` 子路径下共存。

端口占用：本项目只在回环上绑 `127.0.0.1:8001`（后端）与 `127.0.0.1:3300`（前端），
Postgres 与 Neo4j 完全不对外暴露。公网流量一律经 Nginx。

---

## 一、服务器部署步骤

### 1. 拉代码

```bash
git clone <你的仓库地址> RAG_coder && cd RAG_coder
```

### 2. 配置 .env

```bash
cp .env.example .env
```

编辑 `.env`，必改四处：

| 项 | 填什么 |
|---|---|
| `EMBEDDING_API_KEY` / `CHAT_API_KEY` / `RERANK_API_KEY` | **同一个硅基流动 key**，三处都填 |
| `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `MCP_ALLOWED_HOSTS` | 取消注释并**加上你的域名**，见第五节 |
| `NEO4J_PASSWORD` | 改掉默认值（生产不要用 `ragcoder123`） |

模型默认已是硅基流动那套，不用动：

```
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B   EMBEDDING_DIM=4096
CHAT_MODEL=deepseek-ai/DeepSeek-V4-Flash
RERANK_MODEL=Qwen/Qwen3-Reranker-8B
```

`*_BASE_URL` 一律写到 `/v1` 为止、**不要带 `/embeddings` 或 `/rerank` 后缀**——客户端自己拼。

### 3. 起服务

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

首次构建约 3-8 分钟。等健康检查通过：

```bash
docker compose -f docker-compose.prod.yml ps
```

自检（此时还没配 Nginx，直接打回环端口）：

```bash
curl -s http://127.0.0.1:8001/health
```

预期 `{"status":"ok"}`。

### 4. 接进 Nginx

把片段 include 进已有站点的 server 块：

```nginx
server {
    server_name your-domain.com;
    # ...你已有项目的 location...

    include /path/to/RAG_coder/deploy/nginx-rag.conf;
}
```

```bash
nginx -t && nginx -s reload
```

`deploy/nginx-rag.conf` 里 `/rag/api/` 那段的 `proxy_buffering off` 等三行**不能删**——
SSE 经默认缓冲的反代会让聊天变成"一直转圈、最后整段蹦出来"，每行为什么存在都写在注释里了。

### 5. 验收清单

浏览器打开 `https://your-domain.com/rag/`，依次确认：

1. **首页加载** —— 项目列表页出来，样式与图标正常（basePath 生效）
2. **建项目** —— 填 git 地址能创建成功（API 走通）
3. **索引完成** —— 进度条持续推进到 100%，状态变「就绪」
4. **聊天流式** —— 提问后答案**逐字出现**而不是等半天整段蹦出（SSE 未被缓冲）
5. **MCP 握手** —— 见下面第五节

---

## 二、更新部署

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

数据库迁移在容器启动时自动执行（`alembic upgrade head`）。数据都在 named volume 里，重建容器不丢。

---

## 三、日志与排查

```bash
docker compose -f docker-compose.prod.yml logs -f backend
```

几个值得认识的日志：

| 日志 | 含义 |
|---|---|
| `rerank 超时（5.0s），保持原有排序` | 精排降级了，问答仍正常，只是排序回到 RRF |
| `报告 LLM 返回空内容（第 N 次，max_tokens=...）` | 推理型模型把预算吃光了，正文没轮到 |
| `拒绝未鉴权的 MCP 请求` | 配了 `MCP_AUTH_TOKEN` 但客户端没带 header |
| `Invalid Host header` / 421 | MCP 的域名不在 `MCP_ALLOWED_HOSTS` 里，见第五节 |

---

## 四、备份

```bash
docker compose -f docker-compose.prod.yml exec db pg_dump -U raguser ragcoder > backup.sql
docker run --rm -v ragcoder_neo4jdata:/data -v "$PWD":/backup alpine \
  tar czf /backup/neo4j-backup.tar.gz /data
```

（volume 名前缀取决于项目目录名，用 `docker volume ls` 确认。）

---

## 五、MCP 远程接入

Claude Code 接入本实例：

```bash
claude mcp add --transport http rag-coder https://your-domain.com/rag/api/mcp
```

### ⚠️ 必须先把域名加进白名单

后端对 `/mcp` 有 DNS 重绑定防护（MCP 本身无鉴权，这是唯一屏障）。默认白名单只有本机，
**经域名访问会直接返回 421 `Invalid Host header`**——这一点已实测确认，不是配置玄学。

在 `.env` 里：

```
MCP_ALLOWED_HOSTS=["127.0.0.1:*","localhost:*","[::1]:*","backend:*","your-domain.com"]
```

改完重启后端：

```bash
docker compose -f docker-compose.prod.yml up -d backend
```

### 公网暴露建议同时开鉴权

`/mcp` 能读到你所有已索引仓库的代码。公网可达时强烈建议：

```
MCP_AUTH_TOKEN=<python -c "import secrets; print(secrets.token_urlsafe(32))" 生成>
```

客户端相应改成：

```bash
claude mcp add --transport http rag-coder https://your-domain.com/rag/api/mcp \
  --header "Authorization: Bearer <你的 token>"
```

接入信息页 `https://your-domain.com/rag/mcp-guide` 会按当前配置显示正确的命令。

---

## 附录 A：已有实例切换到硅基流动嵌入（1024 → 4096 维）

**只有已经索引过数据的实例需要这一节**；全新部署直接按上面走即可。

嵌入维度变了，而 Neo4j 的向量索引维度是建索引时固定的。启动时的维度校验会拒绝启动并提示
`Neo4j 向量索引 chunk_embedding 维度为 1024，与 EMBEDDING_DIM=4096 不符`。

按顺序执行：

**1. 停后端**（保留 Neo4j 运行）

```bash
docker compose -f docker-compose.prod.yml stop backend
```

**2. 删三个向量索引**（Neo4j Browser 或 cypher-shell）

```cypher
DROP INDEX chunk_embedding IF EXISTS;
DROP INDEX file_summary_embedding IF EXISTS;
DROP INDEX module_summary_embedding IF EXISTS;
```

命令行版本：

```bash
docker compose -f docker-compose.prod.yml exec neo4j cypher-shell -u neo4j -p <密码> \
  "DROP INDEX chunk_embedding IF EXISTS; DROP INDEX file_summary_embedding IF EXISTS; DROP INDEX module_summary_embedding IF EXISTS;"
```

**3. 改 `.env`** 为硅基流动那套（`EMBEDDING_DIM=4096`）

**4. 起后端** —— 启动时按新维度幂等重建三个索引

```bash
docker compose -f docker-compose.prod.yml up -d backend
```

**5. 每个项目强制全量重索引**

```bash
curl -X POST "http://127.0.0.1:8001/projects/<项目 id>/index?mode=full"
```

必须 `mode=full`：旧向量是 1024 维的，留着就是脏数据。

> 换模型后即使走 `mode=auto` 也会被强制转全量（缓存键含模型名与维度，且 auto 判定会检查
> Project 节点上记录的嵌入模型）——但显式 `mode=full` 更省心。

**6. 确认**：任务 stats 里 `embedded_cached` 应为 0（旧缓存键全部失效，确实重算了向量）。

---

## 附录 B：本地开发不受影响

所有路径类 env 默认为空，`docker compose up`（开发版）的本机形态与之前完全一致：
前端 `http://localhost:3000`、后端 `http://localhost:8001`、无子路径、无 rerank
（`RERANK_*` 留空即关闭）。
