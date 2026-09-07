# 生产部署（统一栈 peco）

一台服务器、一个 compose 项目、三个自建镜像。**主路径是自动部署**：push 到 main 即上线；
手工路径只做兜底。本文以 2026-09-07 的形态为准，M7 时代的宿主 Nginx 方式已整体退役，
历史见 `server-notes/README.md`。

## 一、现行形态

```
~/peco                          main 分支的 git clone（不再 rsync）
├─ deploy/docker-compose.yml    基线：零宿主端口、零 restart，本身即生产安全形态
├─ deploy/docker-compose.prod.yml     生产增量：restart、回环端口、内存上限
├─ deploy/docker-compose.server.yml   服务器专有：nginx 占 80/443 + 证书挂载
├─ deploy/compose/{rag,platform}.yml  被基线 include 的服务定义
├─ deploy/nginx/nginx-server.conf     单文件挂载进 nginx 容器
├─ deploy/nginx/projects/*.conf       各项目的 location 片段
├─ deploy/scripts/deploy.sh           部署脚本（自动与手工共用）
├─ services/rag/.env                  后端 env，也是 compose 插值源（deploy/.env 软链指向它）
└─ .env.production                    平台 env
```

三个 `-f` 缺一不可，`prod.yml` 单独用起不来任何服务：

```bash
cd ~/peco && docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml -f deploy/docker-compose.server.yml ps
```

| 服务 | 镜像 | 构建上下文 |
|---|---|---|
| platform | 自建 `peco-platform` | 仓库根 |
| backend | 自建 `peco-backend` | `services/rag` |
| worker | 自建 `peco-worker` | `services/rag`（与 backend 同上下文、**不同镜像**） |
| nginx / db / neo4j / rabbitmq / minio | 官方镜像 | — |

四个数据卷固定叫 `rag_coder_*`——项目名早已改成 `peco`，这个前缀是化石，**不要顺手改整齐**，
改了 `up` 会创建一组新空卷，线上数据「看起来消失」。

## 二、自动部署（主路径）

`.github/workflows/deploy.yml` 在 push 到 main 时触发：

```
push main
  └─ 等 45 秒让 GitHub 注册 CI
  └─ 查本次 commit 的 check runs
       ├─ 全部成功           → 继续
       ├─ 有失败             → 中止，线上不变
       ├─ 仍在跑             → 每 30 秒轮询，上限 15 分钟
       └─ 一个都没有         → 放行（改的是 deploy/ 或文档，本就没有 CI）
  └─ 经受限 SSH key 执行服务器上的 deploy/scripts/deploy.sh
```

脚本按「上次成功部署的 commit → 本次」的 diff 决定范围：

| 改了什么 | 动作 |
|---|---|
| `services/rag/**` | build backend **与** worker → 重建两个容器 |
| `app/` `lib/` `components/` `scripts/` `public/` `fonts/`、根目录的 `*.ts` `package*.json` `Dockerfile` | build platform → 重建 |
| `deploy/nginx/**` | 一次性容器 `nginx -t` 校验 → 强制重建 nginx |
| `deploy/*.yml` `deploy/compose/**` `deploy/rabbitmq.conf` | `compose config -q` 校验 → `up -d` |
| 其余（openspec、Markdown、脚本自身） | 无动作，只推进基准 |

部署完成后检查首页与 `/rag/api/health`，任一非 200 则把 `:previous` 标签切回 `:latest`、
重建容器、以失败退出。成功才写 `~/peco/.last-deployed-sha`；失败不写，下次自动补上这次的变更。

**手动触发**（Actions 页 Run workflow）有两个开关：`skip_ci_check` 跳过 CI 门禁做紧急修复；
`wait_for_jobs` 有索引任务在跑时先等它结束（上限 30 分钟）。默认不等——部署会杀掉运行中的
索引任务，Celery 重投递续跑，但摘要阶段若没走到落盘，那部分 LLM 调用要重烧。脚本会在日志里
记「本次中断 N 个任务」。

**三条已知边界**：回滚点只保留一代；`deploy/` 与文档没有任何自动测试，nginx 配置错误靠
`nginx -t` 拦，compose 错误靠 `config -q` 拦，其余靠健康检查；部署日志在 GitHub Actions
的 run 页面看，服务器上不另存。

## 三、手工部署（兜底）

**等价于自动路径**，脚本含全部护栏（基准 diff、语法校验、回滚点、健康检查）：

```bash
ssh ubuntu@43.167.170.20 'bash ~/peco/deploy/scripts/deploy.sh'
```

要等索引任务结束再部署：

```bash
ssh ubuntu@43.167.170.20 'bash ~/peco/deploy/scripts/deploy.sh wait-jobs'
```

**脚本自己改坏了**（它先 `git merge --ff-only origin/main` 再 `exec` 新版本的自己，坏版本会被
下一次部署用上）：用不受限的人工密钥登录，在 `~/peco` 把脚本 checkout 到上一个好版本再跑：

```bash
ssh ubuntu@43.167.170.20 'cd ~/peco && git checkout HEAD~1 -- deploy/scripts/deploy.sh && bash deploy/scripts/deploy.sh'
```

**完全不用脚本**时，按改动类型手工执行（`C` 代指上面那串三个 `-f` 的前缀）：

| 改了什么 | 命令 |
|---|---|
| 后端代码 | `C build backend worker && C up -d --force-recreate --no-deps backend worker` |
| 平台代码 | `C build platform && C up -d --force-recreate --no-deps platform` |
| `.env` / `.env.production` | `C up -d --force-recreate --no-deps <服务>`（不用 build） |
| nginx 配置 | `C up -d --force-recreate --no-deps nginx`（单文件挂载换了 inode，reload 无效） |
| compose 文件 | `C up -d` |

后端两个服务**必须一起点名**：只 `build backend` 的话 worker 会静默跑旧代码，`up -d` 不给任何提示。

## 四、从零部署一台新服务器

1. 装 docker（含 compose 插件）、git、certbot。
2. `git clone https://github.com/Aimlessly1012/peco-platform.git ~/peco`
3. 两份 env 从样板起：`cp services/rag/.env.example services/rag/.env`，`cp .env.production.example .env.production`，
   按注释填。硬约束：`AUTH_JWT_SECRET` 与平台 `NEXTAUTH_SECRET` **同值**（后端用它验平台签发的
   JWS cookie），`PLATFORM_COOKIE_NAME` 在 https 下是 `__Secure-next-auth.session-token`，
   `SECRET_KEY` 与 `MCP_AUTH_TOKEN` 用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成。
4. `ln -s ../services/rag/.env deploy/.env`——compose 从项目目录读 `.env` 做 `${}` 插值，
   RabbitMQ 与 MinIO 的口令靠它传进容器。
5. 证书：`certbot certonly --standalone -d 域名`（此时 80 未被占用），续期钩子
   `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh` 写 `docker exec peco-nginx-1 nginx -s reload`。
   `nginx-server.conf` 里的域名与证书路径按实际改。
6. 首次起栈：`C up -d --build`，等 `C ps` 全部 running / healthy。
7. 冒烟：首页 200、`/rag` 未登录 307 到 `/login`、`/rag/api/health` 200、`/rag/api/projects` 未登录 401。
   浏览器走一遍 GitHub 登录——OAuth App 的回调地址要登记 `https://域名/api/auth/callback/github`。
8. 接自动部署：生成 deploy key（`ssh-keygen -t ed25519 -C deploy-from-ci`），公钥写入
   `~/.ssh/authorized_keys` 时**必须**带前缀
   `command="/home/ubuntu/peco/deploy/scripts/deploy.sh",restrict `；私钥、主机 IP、用户名、
   `ssh-keyscan -t ed25519 <ip>` 的输出分别存进仓库 Secrets `DEPLOY_SSH_KEY` / `DEPLOY_HOST` /
   `DEPLOY_USER` / `DEPLOY_KNOWN_HOSTS`，然后销毁本地私钥。
9. 手工跑一次 `bash ~/peco/deploy/scripts/deploy.sh` 建立部署基准。

**永远保留至少一把不受限的密钥**，那是脚本坏掉时的唯一退路。

## 五、日志与排查

```bash
C logs -f backend      # 或 worker / platform / nginx
```

| 日志 | 含义 |
|---|---|
| `rerank 超时（5.0s），保持原有排序` | 精排降级了，问答仍正常，排序回到 RRF |
| `报告 LLM 返回空内容（第 N 次，max_tokens=...）` | 推理型模型把预算吃光了，正文没轮到 |
| `拒绝未鉴权的 MCP 请求` | 配了 `MCP_AUTH_TOKEN` 但客户端没带 header |
| `Invalid Host header` / 421 | MCP 的域名不在 `MCP_ALLOWED_HOSTS` 里，见第七节 |
| 部署日志 `⚠ 本次部署将中断 N 个运行中的索引任务` | 按设计不阻塞；这 N 个任务会重投递，摘要成本重复 |
| worker 反复重启、`docker inspect` 的 `RestartCount` 增长 | 大仓库索引撞 768M 内存上限被 OOM 杀，`sudo journalctl -k \| grep oom` 可证 |

后端启动要 30 秒上下（字节码编译加自检），重建后立刻 curl 到 000 是正常的。

## 六、备份

```bash
C exec -T db pg_dump -U raguser ragcoder > backup-$(date +%F).sql
docker run --rm -v rag_coder_neo4jdata:/d:ro -v "$PWD":/b alpine tar czf /b/neo4j-$(date +%F).tgz /d
docker run --rm -v rag_coder_miniodata:/d:ro -v "$PWD":/b alpine tar czf /b/minio-$(date +%F).tgz /d
```

热拷贝的 Neo4j 与 MinIO 目录不保证一致，要可靠的话先 `C stop neo4j minio`。
**任何会动数据的变更（切栈、换嵌入模型、删项目）之前先 `pg_dump`**——只记行数是找不回被
级联删掉的数据的，2026-09-03 已经吃过一次亏。

## 七、MCP 远程接入

```bash
claude mcp add --transport http rag-coder https://baotao.wang/rag/api/mcp \
  --header "Authorization: Bearer <MCP_AUTH_TOKEN>"
```

后端对 `/mcp` 有 DNS 重绑定防护，域名必须在 `services/rag/.env` 的 `MCP_ALLOWED_HOSTS` 里，
否则直接 421。`/mcp` 能读到所有已索引仓库的代码，公网可达就必须开 `MCP_AUTH_TOKEN`。
改 env 后 `C up -d --force-recreate --no-deps backend`。接入信息页 `/rag/mcp` 会按当前配置
显示正确的命令。

## 附录 A：更换嵌入模型或维度（这是数据迁移，不是改配置）

Neo4j 向量索引的维度在建索引时固定；`EMBEDDING_MODEL` 或 `EMBEDDING_DIM` 变了，旧向量整体
作废。代码有两道防护会自动生效：启动时校验索引维度不符就拒绝启动；索引时发现项目记录的模型
与当前不符就强制全量重嵌入。顺着它们走：

```bash
C stop worker                                    # 1. 别让任务写入旧维度向量
C exec neo4j cypher-shell -u neo4j -p <密码> \
  "DROP INDEX chunk_embedding IF EXISTS; DROP INDEX file_summary_embedding IF EXISTS; DROP INDEX module_summary_embedding IF EXISTS;"   # 2.
# 3. 改 services/rag/.env 的 EMBEDDING_MODEL 与 EMBEDDING_DIM（两个一起改）
C up -d --force-recreate --no-deps backend       # 4. 启动时按新维度重建三个索引
C up -d --force-recreate --no-deps worker        # 5.
# 6. 每个项目在 /rag 页面点重索引（接口需平台登录态，裸 curl 打不通）
```

确认：任务 stats 的 `fallback_full_reason` 为 `embedding_model_changed`、`embedded_cached` 为 0。

`SHOW INDEXES` 里还会看到第四个 VECTOR 索引 `entity`（`__Entity__.embedding`）：那是 LlamaIndex 属性图存储自建的，配置里不固定维度，与应用的三个索引无关，**不要 DROP 它**。
迁移代价与项目数成正比，能早换别晚换。选型与验收门槛见 `openspec/changes/switch-cheaper-models/`。

## 附录 B：本地开发

```bash
cd deploy && docker compose up -d      # 默认发现会叠加 override.yml，带开发端口，无 nginx
```

平台直连 `127.0.0.1:3200`，后端直连 `127.0.0.1:9200`。本地 `services/rag/.env` 与 `.env.local`
各自独立于服务器那两份，模型与维度配置可以不同——但拿本地跑出的检索指标去和线上比是没有
意义的，配置指纹不同。
