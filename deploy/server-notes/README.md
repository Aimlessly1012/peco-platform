# 服务器实况（43.167.170.20，2026-08-13 部署）

实际接入方式与 DEPLOY.md 的「宿主 Nginx」假设不同：该服务器没有宿主 Nginx，
80 端口由已有项目 zc_erp 的 web 容器（nginx）占用，配置打在镜像里。实况方案：

1. **容器网络直连**（`docker-compose.server.yml`，服务器上与 prod compose 叠加使用）：
   RAG 前后端挂进 `zc_erp_default` 网络——zc_erp-web 的 nginx 直接 proxy 容器名
   `rag_coder-backend-1:8000` / `rag_coder-frontend-1:3000`，不经宿主端口。
   （127.0.0.1 端口绑定收不到容器网关流量，host-gateway 方案因此不可用）
2. **zc_erp 侧改动**（已备份 `~/zc_erp/docker-compose.yml.bak-m7`）：
   web 服务加挂载 `./nginx-default.conf:/etc/nginx/conf.d/default.conf:ro`；
   完整配置见本目录 `zc-erp-nginx-default.conf`（原有 /api/ 反代保持不动 + rag 两条 location）。
3. **启动命令**（服务器 ~/RAG_coder）：
   docker compose -f docker-compose.prod.yml -f docker-compose.server.yml up -d
4. 坑位记录：改挂载的单文件禁用 sed -i（换 inode 后容器 mount 断链，必须 force-recreate）；
   MCP 鉴权在 --root-path 部署下曾被绕过（auth.py 已修，见 test_root_path_deployment_still_guarded）。


## M12：zc_erp 下线，RAG 自持 80 端口（2026-08-17）

用户要求删除服务器上另一套应用 zc_erp（数据不保留）。**它不是一个普通的删除**：
M7 部署时 80 端口被 zc_erp 的 web 容器占着，RAG 的 `/rag` 路由是寄在**它的 nginx**
里的，RAG 自己的容器只绑 127.0.0.1——直接删会让公网入口整个消失。

执行顺序（先换入口再删，全程留退路）：
1. 从 zc_erp-web-1 里导出 nginx 配置作基础 → 写成 `deploy/nginx-server.conf`
   （上游改用 compose 服务名 backend/frontend，容器重建改名也不断）
2. 重写 `docker-compose.server.yml`：去掉 `zc_erp_default` 外部网络引用（那个网络
   即将随 zc_erp 消失），加 nginx 服务占 80
3. `docker compose stop` zc_erp（先停不删）→ 起 RAG 的 nginx → 公网验证
   （/rag 200、API 401/200、MCP 握手、根路径 302）
4. 验证通过后才 `down -v` 清容器/卷/网络 + 删镜像 + 删目录

**根路径用 302 不用 301**：作品集（heitu-platform）以后要占根路径，301 会被浏览器
永久缓存，届时访客仍被强制弹去 /rag 且清不掉。

回收：磁盘释放约 1.8GB（镜像 1.7GB + 卷），服务器上现在只剩 RAG_coder 一套。


## M12：作品集平台接管根路径，RAG 转为纯后端（2026-08-22）

RAG Coder 并入 peco-platform（Next.js，另一个仓库）。现在服务器上的形态：

```
nginx (rag_coder-nginx-1, 占 80)
  ├─ /            → peco-platform-platform-1:3000   作品集 + /front + /login + /admin + /rag/* 页面
  └─ /rag/api/    → backend:8000                    剥前缀，SSE 三件套照旧
platform 与 backend 共用 rag_coder_default 网络与同一个 Postgres
```

**踩过的两个坑，重装时注意**：
1. `docker-compose.server.yml` 是服务器专有文件（rsync 时被 --exclude），删 prod.yml 里的
   frontend 服务后，这里的 `frontend:` 段与 nginx 的 `depends_on: frontend` 会变成悬空引用，
   compose 直接报 "invalid compose project"、连带迁移都跑不了。改完这两处才恢复。
2. nginx 配置是**单文件挂载**，同步要用 `rsync --inplace`——常规 rsync 换 inode 会让容器里的
   挂载断链，改了等于没改。

**鉴权**：平台的 NextAuth 用 JWS(HS256) 签 cookie，后端用同一个密钥（`AUTH_JWT_SECRET`
= 平台的 `NEXTAUTH_SECRET`）验签。两边密钥必须一致，否则登录后访问 /rag/api 一律 401。

### nginx 容器名解析：必须用 resolver + 变量（2026-08-22 踩坑）

`proxy_pass http://容器名:端口` 只在 nginx 启动/reload 那一刻解析一次并永久缓存。
平台容器一重建 IP 就变（172.19.0.4 → .5），nginx 还往旧地址发 → **全站 502**，
必须手动 `nginx -s reload` 才恢复——每次部署都要多这一步，且中间有一段服务不可用。

修法（已落进 deploy/nginx-server.conf）：

```nginx
resolver 127.0.0.11 valid=10s ipv6=off;      # Docker 内置 DNS
location / {
    set $platform_upstream http://peco-platform-platform-1:3000;
    proxy_pass $platform_upstream;            # 走变量才会按 valid 周期重新解析
}
```

**变量式 proxy_pass 不会自动剥前缀**，`/rag/api/` 那条要显式 `rewrite ^/rag/api/(.*)$ /$1 break;`
补回原先靠末尾斜杠实现的剥前缀。

实测：重建容器后不 reload，公网直接 200。

## 域名与 HTTPS（2026-08-25 上线，同日主域切换 heitu.wang → baotao.wang）

- 主域 `baotao.wang`：**阿里云（万网）注册，解析也在阿里云**——`@` 与 `www` 两条
  A 记录 → 43.167.170.20。教训：域名在哪家注册，解析就加在哪家的 DNS 控制台
  （NS 不迁的话在别家加记录不生效）；国内后缀（.wang）实名认证通过前是
  clientHold，全球 DNS 连 NS 委派都查不到，什么都别排查，先等认证。
  服务器是腾讯云**东京**（ap-tokyo），境外机器，无需 ICP 备案，无公网 IPv6（勿加 AAAA）。
- 旧域 `heitu.wang`（腾讯 DNSPod）整站 301 → baotao.wang；其证书 2026-11 到期，
  若域名不续注册，到期后把 nginx 里 heitu 的 443 块和 80 server_name 里的两个名字删掉即可。
  **2026-09-03 已退役**：用户决定不再使用 heitu.wang。nginx 里 heitu 的 443 块与 80 server_name 的两个名字已删
  （先改 nginx 再 `certbot delete --cert-name heitu.wang`，顺序反了 nginx 会因证书路径缺失起不来），
  DNSPod 的两条 A 记录由用户删除，域名到期不续。此后 https://heitu.wang 若仍解析到本机，会命中 443 的
  首个 server 块并因证书不匹配被浏览器拦下——这是预期，不是故障。
- 入口统一收敛到 `https://baotao.wang`：80 只留 ACME 验证路径，其余（http、www、
  旧域、IP 直访）一律 301。MCP 接入地址：`https://baotao.wang/rag/api/mcp`。
- 证书：宿主机 certbot 2.9.0（apt），`certbot certonly --webroot -w /var/www/certbot`。
  `/etc/letsencrypt` 与 `/var/www/certbot` 以只读挂载进 nginx 容器（见 server.yml）。
  续期靠 apt 自带的 certbot.timer（每日两跑）；**续期后容器不会自己换证书句柄**，
  `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh` 负责 `docker exec rag_coder-nginx-1 nginx -s reload`。
- **cookie 名连带（重要）**：NEXTAUTH_URL 换成 https 后，NextAuth 自动把会话 cookie
  改名为 `__Secure-next-auth.session-token`（http 时代叫 `next-auth.session-token`）。
  后端验签读哪个名字由 RAG `.env` 的 `PLATFORM_COOKIE_NAME` 决定——两边必须同步换，
  只换一边的症状是：平台登录正常、`/rag` 页面能进，但所有 `/rag/api/*` 全 401。
- GitHub OAuth App 的 Authorization callback URL 必须登记 `https://baotao.wang/api/auth/callback/github`。

## M13 任务栈（2026-08-25 上线）：Celery + RabbitMQ + MinIO

- 索引任务在独立 worker 容器执行（Celery，concurrency=1）；backend 只投递。
  三个新容器 mem_limit：rabbitmq 256m / minio 256m / worker 768m。
  实测常驻：rabbitmq ~131M、minio ~142M、worker 空闲 ~187M / 索引峰值 ~275M+，
  上线后全机 available ~1.4G。
- **回滚开关**：RAG `.env` 的 `TASK_QUEUE_ENABLED`。改回 false + 重启 backend
  即回到 M12 进程内行为（索引不再依赖 rabbitmq/worker），不用回退镜像。
- RabbitMQ 内存水位在 deploy/rabbitmq.conf（absolute 192MiB）——**不要**改回
  RABBITMQ_VM_MEMORY_HIGH_WATERMARK 环境变量写法，3.9 起官方镜像见到它直接退出。
- 破坏性验收已做：索引中途 docker restart worker，任务由 RabbitMQ 重投递自动
  续跑（acks_late），摘要/嵌入缓存让重跑快速跳过已完成部分。孤儿 RUNNING 任务
  在 backend 启动时重新入队（不再标 stale-failed）。
- MinIO 凭据在 RAG `.env`（M13 段）；桶 rag-artifacts 启动自动创建。存报告导出件
  （reports/{project_id}.md）与索引产物快照（index-snapshots/...），均非关键路径，
  MinIO 挂了索引照跑、导出照下（只丢留档）。
- worker 与 backend 同镜像：改后端代码后两个都要 build + up -d。

## M14 容量护栏（2026-08-26）

- 双护栏：`PROJECT_LIMIT=8`（主约束，项目数是 Neo4j 内存的代理指标）+ `DISK_MIN_FREE_GB=5`
  （兜底），都在 RAG `.env`。只拦新建项目；重索引/删除不受限。
- 线上验证过：临时调 LIMIT=2 → capacity accepting=false、创建 409 带原因、不落库；调回即恢复。
- **docker-compose.server.yml 已纳入 git 仓库**：它曾是服务器专有文件，2026-08-26 部署时被
  rsync --delete 误删（本文件早前记载的坑第二次咬人）。文件无秘密，入库后 rsync 自然携带。

## worker 镜像的部署坑（2026-08-26 实锤）

worker 服务有自己的 `build: ./backend` 段，compose 给它**独立命名镜像**
`rag_coder-worker`（与 `rag_coder-backend` 是两个镜像）。只
`build backend` 不会更新它——worker 会一直跑旧代码，且 `up -d worker`
/`--force-recreate` 都只是用旧镜像重建容器，毫无提示。
**部署后端代码的标准动作**：`build backend worker` 两个都点名，再 `up -d backend worker`。

## M16 源码 bundle 主存储（2026-08-28）

- MinIO 是源码唯一持久层：`repo-bundles/{project_id}.bundle`（git bundle 全史，固定 key 覆盖写）。
  本地 `data/repos/` 只是任务级临时根，任务尾 finally 清理；worker 启动时兜底清扫孤儿工作区
  （OOM kill 时 finally 不执行）。tarball 归档（repo-archives/）已退役并清空。
- 取码优先级：ls-remote 秒回 → bundle 恢复 + fetch 增量 → 任一环失败 fallback clone 远端。
  线上全链路实测过（`code_source` 字段区分 clone/bundle）。
- compose 的 repos 卷暂保留（观察一周后单独移除）；缓存实证：全量重跑摘要 40/41、嵌入 151/152 命中。
