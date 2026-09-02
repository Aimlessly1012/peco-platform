## MODIFIED Requirements

### Requirement: 生产 Compose 与反代约束

仓库 SHALL 以 override 形式提供生产编排 `deploy/docker-compose.prod.yml`，叠加于统一基线
（`deploy/docker-compose.yml` + `deploy/compose/*.yml`）之上。基线 SHALL NOT 包含宿主端口
映射与重启策略——**基线本身即生产安全形态**；开发用端口映射由
`deploy/docker-compose.override.yml` 提供，仅经 compose 默认发现生效，显式 `-f` 的生产组合
SHALL NOT 加载它。prod 覆盖层只声明生产增量：`restart: unless-stopped`、backend 回环端口、
内存限制与生产环境变量。生产 SHALL 使用容器化 Nginx（`deploy/docker-compose.server.yml`
挂载 `deploy/nginx/nginx-server.conf`）；M7 时代的宿主片段 `nginx-rag.conf` 已退役，
SHALL NOT 再作为活配置分发。Nginx 对后端路由 SHALL 包含 `proxy_buffering off` 与放宽的
`proxy_read_timeout`——SSE 经默认缓冲反代会使聊天流式完全失效。

#### Scenario: SSE 经反代不缓冲

- **WHEN** 通过 Nginx 子路径发起聊天
- **THEN** token 逐段到达浏览器（打字机效果），而非等待整答后一次性返回

#### Scenario: 默认状态落在安全一侧

- **WHEN** 仅以基线渲染（不加载任何覆盖层）
- **THEN** 配置中不存在任何宿主端口映射——忘记叠加覆盖层的最坏后果是本地连不上，而非数据库暴露公网

#### Scenario: 生产覆盖层正确叠加

- **WHEN** 以 `-f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml -f deploy/docker-compose.server.yml` 渲染配置
- **THEN** platform 与 RAG 全部服务位于同一 compose 项目，数据库与 Neo4j 无宿主端口映射，四个数据卷仍渲染为 `rag_coder_*` 原名
