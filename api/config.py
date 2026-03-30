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

    # ── Cloudflare R2 (S3-compatible object storage, zero egress fees) ────────
    # Endpoint format: https://<account_id>.r2.cloudflarestorage.com
    R2_ENDPOINT_URL: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "pointcloud-platform-data"
    # Public base URL for R2 objects (custom domain or r2.dev subdomain)
    # Example: https://assets.yourdomain.com  or  https://pub-<hash>.r2.dev
    R2_PUBLIC_BASE: str = ""

    # ── n8n (optional — workflow automation) ───────────────────────────────────────────────────
    N8N_API_URL: str = ""
    N8N_API_KEY: str = ""
    # Webhook URLs triggered by platform events — set in n8n and paste here
    N8N_PAYMENT_FAILED_WEBHOOK: str = ""
    N8N_NEW_USER_WEBHOOK: str = ""

    # ── Stripe (optional — billing) ───────────────────────────────────────────
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_STARTER_PRICE_ID: str = ""
    STRIPE_PRO_PRICE_ID: str = ""
    STRIPE_ENTERPRISE_PRICE_ID: str = ""

    # ── Internal ──────────────────────────────────────────────────────────────
    API_SECRET_KEY: str = ""


settings = Settings()
