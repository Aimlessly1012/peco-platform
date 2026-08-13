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
