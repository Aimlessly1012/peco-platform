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

    secret_key: str = "dev-secret-key"
    repos_dir: Path = Path("./data/repos")

    retrieval_top_k: int = 8
    chunk_max_tokens: int = 1500
    max_file_bytes: int = 1_000_000


settings = Settings()
