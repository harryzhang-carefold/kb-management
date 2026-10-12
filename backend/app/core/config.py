"""应用配置 — 所有外部依赖连接均从 infra/.env 读取。"""
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 定位 infra/.env（相对 backend/ 的上一级）
_ENV_FILE = Path(__file__).resolve().parents[3] / "infra" / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 应用 ----
    app_name: str = "kb-management"
    app_version: str = "1.0.0"
    debug: bool = False
    secret_key: str = "change-me"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    api_prefix: str = "/api/v1"

    # ---- PostgreSQL ----
    pg_user: str = "kb_admin"
    pg_password: str = "kb_password_2026"
    pg_host: str = "127.0.0.1"
    pg_port: int = 9011
    pg_db: str = "kb_management"

    @property
    def database_url(self) -> str:
        return (
            "postgresql+psycopg2://" + self.pg_user + ":" + self.pg_password
            + "@" + self.pg_host + ":" + str(self.pg_port) + "/" + self.pg_db
        )

    # ---- Redis / Celery ----
    redis_host: str = "127.0.0.1"
    redis_port: int = 6179
    redis_password: Optional[str] = None
    celery_broker_url: str = "redis://:Leaflong2025!@127.0.0.1:6179/3"
    celery_result_backend_url: str = "redis://:Leaflong2025!@127.0.0.1:6179/4"

    @property
    def _redis_auth(self) -> str:
        return (":" + self.redis_password + "@") if self.redis_password else ""

    @property
    def celery_broker(self) -> str:
        if self.celery_broker_url:
            return self.celery_broker_url
        return ("redis://" + self._redis_auth + self.redis_host
                + ":" + str(self.redis_port) + "/1")

    @property
    def celery_result_backend(self) -> str:
        if self.celery_result_backend_url:
            return self.celery_result_backend_url
        return ("redis://" + self._redis_auth + self.redis_host
                + ":" + str(self.redis_port) + "/2")

    @property
    def redis_url(self) -> str:
        return ("redis://" + self._redis_auth + self.redis_host
                + ":" + str(self.redis_port))

    # ---- Elasticsearch ----
    es_host: str = "http://127.0.0.1:9200"
    es_index: str = "kb_chunks"
    es_username: Optional[str] = None
    es_password: Optional[str] = None
    es_vector_dim: int = 3584
    es_request_timeout: int = 30

    # ---- MinIO ----
    minio_endpoint: str = "127.0.0.1:9002"
    minio_access_key: str = "kb_admin"
    minio_secret_key: str = "kb_minio_2026"
    minio_bucket: str = "kb-docs"
    minio_secure: bool = False

    # ---- Embedding ----
    embedding_base_url: str = "http://34.64.61.208:4000/v1"
    embedding_api_key: Optional[str] = None
    embedding_model: str = "gte-qwen2"
    embedding_dim: int = 3584

    # ---- LLM ----
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: Optional[str] = None
    llm_model: str = "deepseek-flash"

    # ---- PageIndex（无向量、树索引 + LLM 推理检索）----
    pageindex_llm_model: str = "deepseek-flash"  # 建树/检索推理专用模型（复用 llm_base_url/api_key）
    pageindex_build_timeout: int = 300    # 建树单次 LLM 调用超时（秒）
    pageindex_retrieve_timeout: int = 60  # 检索推理单次 LLM 调用超时（秒）
    pageindex_retrieve_attempts: int = 3  # 检索选节点「空判定」重试上限（BUG-V4-01：
                                          # 推理型模型对同一 prompt 非确定性返回空数组，
                                          # 空判定先做词面相关性裁定，再做有限重试）

    # ---- 知识库引用（kb citations, V2）----
    kb_view_token_minutes: int = 15          # view_token 有效期（分钟）
    kb_public_base_url: str = "https://agent.carefold.ai/kb-management"  # doc_url 绝对 URL 基址
    kb_mcp_api_key: Optional[str] = None     # MCP 9100 Bearer 密钥（.env 注入，不进 git）

    # ---- RAG 参数 ----
    rag_top_k: int = 10
    rag_top_n: int = 5
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 50
    rag_max_file_size_mb: int = 50  # 兼容旧配置；实际按类型上限见 max_file_size_mb()

    # ---- MinerU 文档解析服务（本地 CPU 部署）----
    mineru_api_url: str = "http://127.0.0.1:9030"
    mineru_backend: str = "pipeline"
    mineru_lang: str = "ch"
    mineru_timeout_seconds: int = 1800

    # ---- 按类型文件大小上限（MB）----
    max_size_pdf_mb: int = 15
    max_size_office_mb: int = 20   # docx / pptx / xlsx
    max_size_image_mb: int = 20    # jpg / png / bmp / webp / tiff
    max_size_text_mb: int = 10     # txt / md / html

    def max_file_size_mb(self, file_type: str) -> int:
        """按解析后 file_type 返回上传大小上限（MB）。"""
        if file_type == "pdf":
            return self.max_size_pdf_mb
        if file_type in ("docx", "pptx", "xlsx"):
            return self.max_size_office_mb
        if file_type in ("jpg", "png", "bmp", "webp", "tiff"):
            return self.max_size_image_mb
        return self.max_size_text_mb

    # ---- CORS ----
    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
