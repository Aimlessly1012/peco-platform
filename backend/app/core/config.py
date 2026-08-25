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
    # 问答「生成」环节用模型，空则复用 chat_model。推理型模型首字慢（实测 13s），
    # 代码专用非推理模型 Qwen3-Coder-30B-A3B-Instruct 实测 0.9s 且引用标注更规范。
    # 理解/分类与摘要不受影响，仍走各自配置
    generate_model: str = ""
    summary_concurrency: int = 4

    # M7 D2：检索精排。base_url/api_key/model 任一为空 = 关闭（行为与 M6 完全一致）。
    # base_url 不带资源后缀，客户端自己拼 /rerank
    rerank_base_url: str = ""
    rerank_api_key: str = ""
    rerank_model: str = ""
    # 5s 实测经常超时（16 篇 + 8B 重排 + 跨境），精排一直静默降级等于白配
    rerank_timeout_seconds: float = 15
    rerank_max_chars: int = 1500      # 单篇文档截断：8B 重排模型上下文有限，长文不增益
    rerank_candidate_multiplier: int = 3  # 候选池 = top_k × 这个倍数
    # 送进生成 prompt 的资料总字符预算：实测 16 条 ≈ 7600 字符，是首字延迟的
    # 主要成本。rerank 已把最相关的排在前面，砍掉尾部长尾对答案影响小
    context_char_budget: int = 6000
    context_min_items: int = 4        # 预算再紧也至少给这么多条，别让资料不够答不出

    @property
    def platform_auth_enabled(self) -> bool:
        """M12：平台 GitHub 登录态是否启用（AUTH_JWT_SECRET 为空 = 关闭）。"""
        return bool(self.auth_jwt_secret)

    @property
    def rerank_enabled(self) -> bool:
        return bool(self.rerank_base_url and self.rerank_api_key and self.rerank_model)

    # M4 D7：单次模型调用超时。不设时 SDK 默认 600s，一次挂起就能让整个阶段静止十分钟
    llm_timeout_seconds: float = 60
    embedding_timeout_seconds: float = 30

    # 嵌入输入按字符截断上限。text-embedding-v2 单条上限 2048 token，
    # 中文最坏密度 ~1.5 字符/token → 3000 字符安全；换 8192 上限的模型可调大
    embedding_max_chars: int = 3000

    # M8：JWT 签名密钥。生产必须改成 32+ 字节随机串，否则登录态可被伪造
    secret_key: str = "dev-secret-key"

    # M8：管理员初始化。仅在库中没有 admin 时生效；已有 admin 后改这里不会覆盖
    admin_username: str = "admin"
    admin_password: str = ""

    # M12 D2：接受 peco-platform 的 GitHub 登录态。
    # 与平台 NEXTAUTH_SECRET 同值；为空 = 完全关闭，只走 M8 的密码登录（迁移期退路）。
    # 平台把 NextAuth 默认的 JWE 换成了 JWS(HS256)，这里用 pyjwt 直接验签
    auth_jwt_secret: str = ""
    # 生产是 HTTP，cookie 名没有 __Secure- 前缀；上 HTTPS 后平台会改成 __Secure-next-auth.session-token
    platform_cookie_name: str = "next-auth.session-token"

    # M13：任务队列（Celery + RabbitMQ）。False = 旧的进程内 asyncio 路径，
    # 这是部署回滚开关：生产出问题时改回 False 即回到 M12 行为，不用回退镜像
    task_queue_enabled: bool = False
    rabbitmq_url: str = "amqp://rag:ragpass@rabbitmq:5672//"

    # M13：MinIO 对象存储（报告导出件 + 索引产物归档，均非关键路径）。
    # access key 为空 = 完全禁用，所有存储调用降级为 no-op
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "rag-artifacts"
    minio_secure: bool = False

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
