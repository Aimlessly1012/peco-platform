#!/bin/bash
# 生产部署脚本（change: auto-deploy-from-ci）
#
# 由 GitHub Actions 经受限 SSH key 调用，也可在服务器上手工执行。
# authorized_keys 里以 command="<本文件绝对路径>",restrict 绑定，因此持有部署私钥
# 的一方只能触发部署，不能执行任意命令——仓库是公开的，凭据按可能泄露来设计。
#
# 退出码：0 成功或无需部署；非 0 表示失败（含健康检查未过并已回滚）。
set -uo pipefail

REPO="${DEPLOY_REPO:-$HOME/peco}"
SHA_FILE="$REPO/.last-deployed-sha"
HEALTH_PLATFORM="${DEPLOY_HEALTH_PLATFORM:-https://baotao.wang/}"
HEALTH_BACKEND="${DEPLOY_HEALTH_BACKEND:-https://baotao.wang/rag/api/health}"
MIN_FREE_MB="${DEPLOY_MIN_FREE_MB:-900}"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
die() { log "✘ $*"; exit 1; }

# ── 自举：先更新代码，再用新版本的自己接管 ────────────────────────
# 正在执行的脚本文件被 git 替换不会影响当前进程（fd 指向旧 inode），所以这里
# 显式 exec 一次，确保后续逻辑用的是刚拉下来的版本。DEPLOY_REEXEC 防无限递归。
if [ "${DEPLOY_REEXEC:-}" != "1" ]; then
    cd "$REPO" || die "仓库目录不存在：$REPO"
    log "拉取 main"
    git fetch -q origin main || die "git fetch 失败"
    git checkout -q main 2>/dev/null
    git merge -q --ff-only origin/main || die "git merge --ff-only 失败（工作区有本地改动？）"
    exec env DEPLOY_REEXEC=1 bash "$REPO/deploy/scripts/deploy.sh" "$@"
fi

cd "$REPO" || die "仓库目录不存在：$REPO"
COMPOSE=(docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.prod.yml -f deploy/docker-compose.server.yml)
HEAD_SHA="$(git rev-parse HEAD)"
log "HEAD ${HEAD_SHA:0:7}  $(git log -1 --format=%s | cut -c1-60)"

# ── 变更范围 ────────────────────────────────────────────────────
# 基准取「上次成功部署的 commit」而非 HEAD~1：连推三次只有最后一次部署成功时，
# 按 HEAD~1 算会漏掉中间两次的改动。基准缺失（首次运行）时退化为全量。
BASE=""
[ -f "$SHA_FILE" ] && BASE="$(cat "$SHA_FILE")"
if [ -n "$BASE" ] && git cat-file -e "$BASE^{commit}" 2>/dev/null; then
    CHANGED="$(git diff --name-only "$BASE" "$HEAD_SHA")"
    log "变更基准 ${BASE:0:7} → ${HEAD_SHA:0:7}（$(echo "$CHANGED" | grep -c . ) 个文件）"
else
    CHANGED="__ALL__"
    log "无有效部署基准，本次按全量处理"
fi

matches() { [ "$CHANGED" = "__ALL__" ] && return 0; echo "$CHANGED" | grep -qE "$1"; }

DO_BACKEND=false; DO_PLATFORM=false; DO_NGINX=false; DO_COMPOSE=false
matches '^services/rag/' && DO_BACKEND=true
matches '^(app|components|lib|scripts|public|fonts)/|^(middleware|next\.config|tailwind\.config|tsconfig)\.|^package(-lock)?\.json$|^Dockerfile$' && DO_PLATFORM=true
matches '^deploy/nginx/' && DO_NGINX=true
matches '^deploy/(docker-compose[^/]*\.yml|compose/|rabbitmq\.conf)' && DO_COMPOSE=true

log "范围：backend/worker=$DO_BACKEND platform=$DO_PLATFORM nginx=$DO_NGINX compose=$DO_COMPOSE"
if ! $DO_BACKEND && ! $DO_PLATFORM && ! $DO_NGINX && ! $DO_COMPOSE; then
    log "无需部署（仅文档或 openspec 变更）"
    echo "$HEAD_SHA" > "$SHA_FILE"
    exit 0
fi

# ── 部署前记账：被中断的索引任务 ────────────────────────────────
# 按决策不阻塞部署。但被中断的任务重跑时，若上一轮没走到 graph 阶段，摘要结果
# 未落盘、缓存为空，那部分 LLM 调用要全价重烧——不记下来就会以「账单莫名偏高」
# 的形式沉默流失。
RUNNING="$(docker exec peco-db-1 psql -U raguser -d ragcoder -Atc \
    "select count(*) from index_jobs where status='running';" 2>/dev/null || echo '?')"
if [ "$RUNNING" != "0" ] && [ "$RUNNING" != "?" ]; then
    log "⚠ 本次部署将中断 $RUNNING 个运行中的索引任务：队列会重投递续跑，但摘要阶段的调用成本会重复产生"
elif [ "$RUNNING" = "?" ]; then
    log "⚠ 无法查询运行中任务数（db 容器不可达），继续部署"
fi

# ── 构建前腾资源 ────────────────────────────────────────────────
FREE_MB="$(free -m | awk '/^Mem:/{print $7}')"
log "可用内存 ${FREE_MB}M"
if { $DO_BACKEND || $DO_PLATFORM; } && [ "${FREE_MB:-0}" -lt "$MIN_FREE_MB" ]; then
    log "低于 ${MIN_FREE_MB}M，先清理构建缓存"
    docker builder prune -f >/dev/null 2>&1
    log "清理后可用 $(free -m | awk '/^Mem:/{print $7}')M"
fi

# ── 回滚点：把当前镜像打上 :previous ────────────────────────────
# 单机只剩 1.3G 可用内存，跑两份后端容器做蓝绿不现实，标签切换是这台机器上
# 唯一可行的回滚形态。只保留一代——连续两次坏部署时人本来就该介入了。
ROLLBACK_IMAGES=()
tag_previous() {
    for img in "$@"; do
        if docker image inspect "$img:latest" >/dev/null 2>&1; then
            docker tag "$img:latest" "$img:previous" && ROLLBACK_IMAGES+=("$img")
        fi
    done
}
$DO_BACKEND  && tag_previous peco-backend peco-worker
$DO_PLATFORM && tag_previous peco-platform
[ ${#ROLLBACK_IMAGES[@]} -gt 0 ] && log "回滚点已标记：${ROLLBACK_IMAGES[*]}"

# ── 配置语法先于生效 ────────────────────────────────────────────
"${COMPOSE[@]}" config -q || die "docker compose config 校验失败，未做任何改动"

# nginx 配置的语法 compose 查不出来（那是 nginx 的事），而 nginx 分支不构建镜像、
# 没有镜像回滚点——配置写错就只能等健康检查失败后人工救。用一次性容器按相同挂载
# 先 nginx -t，把错误拦在重建之前。
if $DO_NGINX; then
    log "校验 nginx 配置"
    docker run --rm \
        -v "$REPO/deploy/nginx/nginx-server.conf:/etc/nginx/conf.d/default.conf:ro" \
        -v "$REPO/deploy/nginx/projects:/etc/nginx/projects:ro" \
        -v /etc/letsencrypt:/etc/letsencrypt:ro \
        -v /var/www/certbot:/var/www/certbot:ro \
        nginx:alpine nginx -t 2>&1 | sed 's/^/    /' \
        || die "nginx 配置语法错误，未做任何改动"
fi

# ── 构建与重建 ──────────────────────────────────────────────────
# backend 与 worker 共用 services/rag 构建上下文，但 compose 给它们独立镜像：
# 只 build backend 的话 worker 会静默跑旧代码，且 up -d 不给任何提示。
if $DO_BACKEND; then
    log "构建 backend worker"
    "${COMPOSE[@]}" build backend worker || die "后端镜像构建失败"
fi
if $DO_PLATFORM; then
    log "构建 platform"
    "${COMPOSE[@]}" build platform || die "平台镜像构建失败"
fi

RECREATE=()
$DO_BACKEND  && RECREATE+=(backend worker)
$DO_PLATFORM && RECREATE+=(platform)
# nginx 配置是单文件 bind mount：git 更新文件会换 inode，容器里挂的仍是旧的那个，
# 不 force-recreate 等于没改。
$DO_NGINX    && RECREATE+=(nginx)

if [ ${#RECREATE[@]} -gt 0 ]; then
    log "重建容器：${RECREATE[*]}"
    "${COMPOSE[@]}" up -d --force-recreate --no-deps "${RECREATE[@]}" || die "容器重建失败"
fi
if $DO_COMPOSE; then
    log "应用 compose 变更"
    "${COMPOSE[@]}" up -d || die "compose up 失败"
fi

# ── 健康检查 ────────────────────────────────────────────────────
# 自己写重试循环，不用 curl 的 --retry：--max-time 限制的是**整个操作**（含重试），
# 两者一起用会让重试根本没机会跑完就被截断，返回空码。backend 重建后要 30 秒上下
# 才就绪（uvicorn 启动 + 字节码编译），照那样写必然误判为部署失败并触发无谓回滚。
check() {
    local url="$1" name="$2" code="" i
    for i in $(seq 1 40); do
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null)" || code=""
        [ "$code" = "200" ] && break
        sleep 3
    done
    log "  $name → ${code:-无响应}（${i} 次尝试）"
    [ "$code" = "200" ]
}
log "健康检查"
OK=true
check "$HEALTH_PLATFORM" "平台首页" || OK=false
check "$HEALTH_BACKEND"  "后端 health" || OK=false

if ! $OK; then
    log "健康检查未过，回滚"
    if [ ${#ROLLBACK_IMAGES[@]} -gt 0 ]; then
        for img in "${ROLLBACK_IMAGES[@]}"; do
            docker tag "$img:previous" "$img:latest" && log "  $img 已切回 previous"
        done
        [ ${#RECREATE[@]} -gt 0 ] && "${COMPOSE[@]}" up -d --force-recreate --no-deps "${RECREATE[@]}"
        check "$HEALTH_PLATFORM" "回滚后 平台首页"
        check "$HEALTH_BACKEND"  "回滚后 后端 health"
    else
        log "  无镜像回滚点（本次未构建镜像），需人工处理"
    fi
    # 不写 sha：下次部署仍以上一个成功点为基准，不会漏掉本次的变更
    die "部署失败已回滚，未更新部署基准"
fi

echo "$HEAD_SHA" > "$SHA_FILE"
log "✔ 部署完成 ${HEAD_SHA:0:7}"
