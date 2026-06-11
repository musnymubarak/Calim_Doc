"""Application settings, loaded from environment / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Infra
    database_url: str = "postgresql+asyncpg://contract:contract@db:5432/contract"
    redis_url: str = "redis://redis:6379/0"

    # Gemini (legacy RAG engine — unused on the NotebookLM branch, kept for fallback)
    gemini_api_key: str = ""
    gemini_model_fast: str = "gemini-2.5-flash"
    gemini_model_accurate: str = "gemini-2.5-pro"
    # Weakest tier — used ONLY as a last-resort fallback when stronger models are sustained-503.
    gemini_model_lite: str = "gemini-2.5-flash-lite"
    # Stable fallback used when the primary model returns a sustained 503 ("high demand").
    gemini_model_fallback: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768

    # NotebookLM engine — HTTP REST API exposed by the NotebookLM MCP/automation server
    # (e.g. roomi-fields/notebooklm-mcp). Runs a headed Chrome logged into a Google account.
    notebooklm_api_url: str = "http://notebooklm:3000"
    notebooklm_request_timeout: float = 600.0   # answers can take minutes

    # Full-text (BM25) backend: 'pg_search' (ParadeDB, prod/Docker) or 'tsvector'
    # (Postgres built-in, for local runs on vanilla Postgres without ParadeDB).
    fts_backend: str = "pg_search"

    # File storage (local FS on the VPS volume; no S3)
    file_storage_dir: str = "/data/files"

    # Reranker (self-hosted cross-encoder service)
    reranker_url: str = "http://reranker:8080"

    # Cost guardrails
    max_context_tokens: int = 12_000
    max_output_tokens: int = 8_192
    daily_spend_limit_usd: float = 50.0
    per_user_daily_token_limit: int = 2_000_000


settings = Settings()
