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
