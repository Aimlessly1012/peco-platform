# 生产部署

子路径 /rag 形态的生产部署约束（M7 起，M12 后由 peco-platform 承担页面、nginx 统一入口，API 前缀语义不变）。

### Requirement: 子路径部署形态
系统 SHALL 支持以 Nginx 子路径（约定 `/rag`）方式与既有项目共存于同一服务器：前端经 Next.js `basePath`（构建期 env `NEXT_PUBLIC_BASE_PATH`）适配、前端 API 地址支持相对路径（`NEXT_PUBLIC_API_BASE=/rag/api`）、后端经 uvicorn `--root-path`（env `ROOT_PATH`）适配文档地址。所有路径 env 默认为空，空值行为 SHALL 与本机开发形态完全一致。

#### Scenario: 子路径全链路可用
- **WHEN** 按 DEPLOY.md 配置 Nginx 后访问 `https://域名/rag/`
- **THEN** 页面静态资源、API 请求、SSE 聊天流均在 `/rag` 前缀下正常工作，与已有项目互不干扰

#### Scenario: 本机开发不受影响
- **WHEN** 路径类 env 全部为空（默认）
- **THEN** `docker compose up` 的本机形态行为与 M6 一致

### Requirement: 生产 Compose 与反代约束
仓库 SHALL 提供 `docker-compose.prod.yml`（数据库与 Neo4j 不映射宿主端口、应用端口仅绑定 127.0.0.1、`restart: unless-stopped`、无开发卷挂载）与 Nginx 配置片段 `deploy/nginx-rag.conf`。Nginx 片段对后端路由 SHALL 包含 `proxy_buffering off` 与放宽的 `proxy_read_timeout`——SSE 经默认缓冲反代会使聊天流式完全失效。

#### Scenario: SSE 经反代不缓冲
- **WHEN** 通过 Nginx 子路径发起聊天
- **THEN** token 逐段到达浏览器（打字机效果），而非等待整答后一次性返回

### Requirement: 生产部署文档
仓库 SHALL 提供 `deploy/DEPLOY.md`：服务器步骤（clone → `.env` 填硅基流动 key → prod compose 启动 → Nginx include → 验收清单）、MCP 远程接入安全项（`MCP_ALLOWED_HOSTS` 必须加服务器域名，公网建议配 `MCP_AUTH_TOKEN`）、以及本地切换硅基流动嵌入时的向量索引重建附录（维度 1024→4096 会触发启动维度校验拒启）。

#### Scenario: 照文档一次部署成功
- **WHEN** 用户按 DEPLOY.md 从零执行到验收清单
- **THEN** 每一步命令可直接复制执行，验收清单覆盖：首页、建项目、索引完成、聊天流式、MCP 握手
