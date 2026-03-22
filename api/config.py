"""
Application configuration — reads from environment variables with sensible defaults.
All secrets are injected via Railway environment variables in production.
"""
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    ENVIRONMENT: str = "production"
    APP_DOMAIN: str = "https://frontend-production-4daa.up.railway.app"

    # ── Supabase ──────────────────────────────────────────────────────────────
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # ── OpenAI ────────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""

    # ── AWS (optional — S3/SQS for file upload and job queuing) ──────────────
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET_NAME: str = ""
    SQS_QUEUE_URL: str = ""

    # ── n8n (optional — workflow automation) ─────────────────────────────────
    N8N_API_URL: str = ""
    N8N_API_KEY: str = ""


settings = Settings()
