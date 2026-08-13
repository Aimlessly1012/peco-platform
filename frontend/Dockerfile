FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .

# NEXT_PUBLIC_* 会被编译进产物，必须在 build 阶段就位——运行期再注入是无效的。
# 两者都留空 = 本机开发形态（无子路径、API 打 http://localhost:8001）。
# 子路径部署示例：--build-arg NEXT_PUBLIC_BASE_PATH=/rag --build-arg NEXT_PUBLIC_API_BASE=/rag/api
ARG NEXT_PUBLIC_BASE_PATH=""
ARG NEXT_PUBLIC_API_BASE=""
ENV NEXT_PUBLIC_BASE_PATH=$NEXT_PUBLIC_BASE_PATH \
    NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
# 没有 public/：自托管字体走 webpack（frontend/fonts/ → .next/static/media），
# 这样 basePath 子路径部署时资源前缀才会跟着变。
EXPOSE 3000
CMD ["node", "server.js"]
