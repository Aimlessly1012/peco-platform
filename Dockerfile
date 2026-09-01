FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# 构建期不需要真实数据库与 OAuth 凭据：本项目所有敏感配置都在运行时读取
# （没有 NEXT_PUBLIC_* 编译进产物），所以这里不传任何 build-arg
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
# Next standalone 用 HOSTNAME 决定监听地址，容器里它默认是容器 ID，
# 多网络时会只绑其中一个网段导致 nginx 502（RAG 前端踩过，见 deploy/server-notes）
ENV HOSTNAME=0.0.0.0 PORT=3000
# build 阶段的 distDir 是 .next-build（.next 留给 dev，见 next.config.ts）
COPY --from=builder /app/.next-build/standalone ./
COPY --from=builder /app/.next-build/static ./.next-build/static
COPY --from=builder /app/migrations ./migrations
COPY --from=builder /app/scripts ./scripts
EXPOSE 3000
CMD ["node", "server.js"]
