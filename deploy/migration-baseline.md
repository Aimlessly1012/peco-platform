# 迁移数据基线（merge-rag-backend 任务 1.1）

**采集时间**：2026-09-01 17:47 CST · **主机**：本地开发机（darwin）· **Docker**：29.6.1

这份基线是「数据没丢」的唯一判据。切换后的比对以本文数字为准，不靠临场记忆
（design D5 / R1）。服务器侧需在切换窗口开始前用同样的命令再采一份（任务 5.1）。

---

## 1. 数据卷

宿主共 50 个卷，其中本次迁移关心的四个：

| 卷名（实名） | 大小 | 创建时间 | 承载 |
|---|---|---|---|
| `rag_coder_pgdata` | 46.8 MB | 2026-08-13T06:53:33Z | Postgres：平台用户 + RAG 业务表 |
| `rag_coder_neo4jdata` | 1.0 GB | 2026-08-13T06:53:33Z | Neo4j：代码图谱 + 向量 |
| `rag_coder_miniodata` | 292 KB | 2026-08-25T09:40:57Z | MinIO：源码 bundle（**当前为空，见 §5**） |
| `rag_coder_rabbitmqdata` | 288 KB | 2026-08-25T09:40:57Z | RabbitMQ：Celery broker |

四个卷名的 `rag_coder_` 前缀来自旧目录名派生的 compose 项目名。**切换后这四个名字必须
逐字不变**——这是 D2 的全部要点，也是本 change 唯一可能丢数据的地方。

复现命令：

```bash
docker volume ls --format '{{.Name}}' | grep '^rag_coder_' | sort
docker volume inspect rag_coder_pgdata --format '{{.CreatedAt}}'
docker run --rm -v rag_coder_pgdata:/d:ro alpine du -sh /d
```

## 2. Postgres（容器 `rag_coder-db-1`，库 `ragcoder`）

精确 `count(*)`，非 `pg_stat` 估算值：

| 表 | 行数 |
|---|---|
| `platform_users` | **1** |
| `users`（M8 遗留） | 3 |
| `projects` | 3 |
| `chat_sessions` | 5 |
| `chat_messages` | 9 |
| `index_jobs` | 8 |
| `understanding_reports` | 1 |

`alembic_version` = **0010**（迁移版本，切换后必须一致，不得被意外升降级）。

```bash
docker exec rag_coder-db-1 psql -U raguser -d ragcoder -tAc \
  "select 'platform_users='||(select count(*) from platform_users)
       || ' users='||(select count(*) from users)
       || ' projects='||(select count(*) from projects)
       || ' chat_sessions='||(select count(*) from chat_sessions)
       || ' chat_messages='||(select count(*) from chat_messages)
       || ' index_jobs='||(select count(*) from index_jobs)
       || ' understanding_reports='||(select count(*) from understanding_reports)
       || ' alembic_version='||(select version_num from alembic_version);"
```

## 3. Neo4j（容器 `rag_coder-neo4j-1`）

| 指标 | 数量 |
|---|---|
| 节点 | **193** |
| 关系 | **271** |

关系数一并记录：只比节点数的话，关系丢失而节点完整这种情况会漏过去。

```bash
docker exec rag_coder-neo4j-1 cypher-shell -u neo4j -p ragcoder123 --format plain \
  "MATCH (n) RETURN count(n);"
docker exec rag_coder-neo4j-1 cypher-shell -u neo4j -p ragcoder123 --format plain \
  "MATCH ()-[r]->() RETURN count(r);"
```

## 4. MinIO / RabbitMQ

两个容器**采集时均未运行**（`docker ps` 只有 db 与 neo4j）。改为挂载卷只读清点，
不启动服务：

| bucket | 对象数 | 大小 |
|---|---|---|
| `rag-artifacts` | **0** | 4 KB（空目录） |

卷内除 `.minio.sys` 元数据外无任何文件。RabbitMQ 卷 288 KB，是 broker 元数据，
队列内容本就不需要跨迁移保留。

```bash
docker run --rm -v rag_coder_miniodata:/d:ro alpine sh -c \
  'find /d -type f -not -path "*/.minio.sys/*" | wc -l'
```

## 5. 采集中发现的两处异常

记录在此是因为它们影响后续判断，不属于本 change 要修的范围。

### 5.1 MinIO 是空的，与「M16 后主存储在 MinIO」不符

`projects` 有 3 行、`index_jobs` 有 8 行，说明索引跑过；但 `rag-artifacts` 里一个对象都没有。
可能是 bundle 被清理过、或 M16 的存储路径实际未被走到。

**对迁移的影响是正面的**：MinIO 卷无数据可丢，风险低于 design 的预估。但切换后
若 `rag-artifacts` 仍为空，**不能据此判定「数据没丢」**——它本来就是空的。
真要验证 MinIO 链路，得在切换后跑一次索引看有没有对象落进来。

### 5.2 `deploy/nginx-rag.conf` 是死配置（**本节已更正**）

初次采集时我只看了 repo 里的文件，据此判断「nginx 把 `/rag` 指向已退役的 3300，
线上可能仍在跑旧前端」。**这个判断是错的**，subtree 并入 RAG 历史后查证如下：

服务器上生效的是 **`deploy/nginx-server.conf`**（由 `docker-compose.server.yml` 挂载为
容器 nginx 的 `default.conf`）。它的 `/rag` 页面 location 已在 **`8e0c946`**
（2026-08-22，「nginx 把 /rag 交给平台，旧前端路由下线（阶段二完成）」）删除，
`/rag/*` 落到 `location /` 由 peco-platform 处理，`/rag/api/` 因前缀更长仍优先转 FastAPI。
该 commit 的 message 附有公网复测记录：`/rag`、`/rag/mcp`、`/rag/projects` 未登录全部
307 跳登录，带登录态 API 200、SSE 首 token 4.3s、MCP 握手成功。

`nginx-rag.conf` 则是 M7 时代的**子路径接入片段**，用法是 `include` 进宿主已有的
server 块（见 `DEPLOY.md:72`），走宿主回环端口 `127.0.0.1:8001/3300`。M12 改用容器化
nginx + compose 服务名之后它就没有消费者了——**全仓没有任何 compose 挂载它**。

所以线上没有问题，3300 那行只是死文件里的死配置。真正遗留的是另一件事：
`openspec/specs/deployment/spec.md:17` 仍把 `deploy/nginx-rag.conf` 写成 SHALL 提供的
交付物。spec 与实际的这处分叉不在本 change 范围（D3），但值得单独处理。

**教训记在这里**：只读 repo 当前状态而不查历史，会把「早已解决的问题」误报成「线上事故」。
这次是 subtree 并入让 RAG 的 77 个 commit 本地可查才纠正过来的——D1 选 subtree 而非
拷贝重建，收益在这里第一次兑现。

---

## 切换后比对清单（任务 4.1 / 5.3 用）

- [ ] `docker volume ls` 中四个 `rag_coder_*` 卷**全部存在且无新增同类卷**
- [ ] `platform_users` = 1，`users` = 3，`projects` = 3，`chat_sessions` = 5，`chat_messages` = 9，`index_jobs` = 8，`understanding_reports` = 1
- [ ] `alembic_version` = 0010
- [ ] Neo4j 节点 = 193，关系 = 271
- [ ] MinIO `rag-artifacts` 存在（对象数仍为 0 属正常，见 §5.1）
