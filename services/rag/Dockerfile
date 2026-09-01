FROM python:3.12-slim

# git 供 GitPython clone 仓库使用
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# 用 PyPI 装 uv，不再 COPY --from=ghcr.io（ghcr 在部分网络 TLS 超时，
# 且 latest 标签每次 build 都要联网查 manifest——正是"build 静默失败"的根因）
RUN pip install --no-cache-dir uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

COPY . .
RUN uv sync --no-dev

EXPOSE 8000
# ROOT_PATH 供 Nginx 子路径部署（M7 D3）：只影响 openapi.json / docs 里的地址生成，
# 路由本身不加前缀（Nginx 已剥掉前缀再转发）。默认空 = 本机形态不变
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --root-path \"${ROOT_PATH:-}\""]
