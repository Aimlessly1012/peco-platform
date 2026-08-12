from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://raguser:ragpass@localhost:5433/ragcoder"

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "ragcoder123"

    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024
    embedding_batch_size: int = 10
    embedding_concurrency: int = 4

    chat_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    chat_api_key: str = ""
    chat_model: str = "qwen3.7-plus"

    summary_model: str = ""  # 摘要用模型，空则复用 chat_model
    summary_concurrency: int = 4

    # M4 D7：单次模型调用超时。不设时 SDK 默认 600s，一次挂起就能让整个阶段静止十分钟
    llm_timeout_seconds: float = 60
    embedding_timeout_seconds: float = 30

    # 嵌入输入按字符截断上限。text-embedding-v2 单条上限 2048 token，
    # 中文最坏密度 ~1.5 字符/token → 3000 字符安全；换 8192 上限的模型可调大
    embedding_max_chars: int = 3000

    secret_key: str = "dev-secret-key"
    repos_dir: Path = Path("./data/repos")

    retrieval_top_k: int = 8
    chunk_max_tokens: int = 1500
    max_file_bytes: int = 1_000_000

    # MCP（M3）：DNS 重绑定防护白名单。MCP 无鉴权，必须限制 Host/Origin，
    # 否则浏览器里的恶意页面可直接读取本地代码库。默认放行本机与 compose 内部服务名。
    mcp_allowed_hosts: list[str] = [
        "127.0.0.1:*", "localhost:*", "[::1]:*", "backend:*",
    ]
    mcp_allowed_origins: list[str] = [
        "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
    ]
    # M4 D7：非空时 /mcp 需要 Authorization: Bearer <token>。默认空 = 本地免鉴权
    mcp_auth_token: str = ""


settings = Settings()
