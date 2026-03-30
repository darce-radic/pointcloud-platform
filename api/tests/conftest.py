"""
Pytest configuration for the PointCloud Platform API test suite.

Key design decisions:
- All environment variables are set BEFORE any application code is imported.
- get_supabase() is decorated with @lru_cache, so we must clear the cache
  and replace it with a MagicMock via dependency_overrides to prevent real
  HTTP connections to Supabase during tests.
- get_current_user is overridden globally so all tests skip JWT validation.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

# ── Environment variables (must be set before any app import) ─────────────────
os.environ["SUPABASE_URL"] = "http://test-supabase-url"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "test-service-key"
os.environ["SUPABASE_ANON_KEY"] = "test-anon-key"
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_xxx"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
os.environ["N8N_PAYMENT_FAILED_WEBHOOK"] = "http://localhost/webhook/payment-failed"
os.environ["N8N_NEW_USER_WEBHOOK"] = "http://localhost/webhook/new-user"
os.environ["N8N_API_URL"] = "http://localhost:5678"
os.environ["N8N_API_KEY"] = "test-n8n-key"
os.environ["APP_DOMAIN"] = "http://localhost:5173"
os.environ["ENVIRONMENT"] = "test"
os.environ["AWS_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "test"
os.environ["AWS_SECRET_ACCESS_KEY"] = "test"
os.environ["S3_BUCKET_NAME"] = "test-bucket"
os.environ["SQS_QUEUE_URL"] = "http://localhost:4566/000000000000/test.fifo"
os.environ["R2_ENDPOINT_URL"] = "http://localhost:9000"
os.environ["R2_ACCESS_KEY_ID"] = "test"
os.environ["R2_SECRET_ACCESS_KEY"] = "test"
os.environ["R2_BUCKET_NAME"] = "test-bucket"
os.environ["R2_PUBLIC_BASE_URL"] = "http://localhost:9000/test-bucket"

# ── App imports (after env vars are set) ──────────────────────────────────────
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402
from dependencies import get_current_user, get_supabase, AuthenticatedUser  # noqa: E402

# ── Global mock Supabase client ───────────────────────────────────────────────
# This is the default mock. Individual tests that need specific return values
# should override app.dependency_overrides[get_supabase] in their own scope.
_DEFAULT_MOCK_SUPABASE = MagicMock()

# ── Global mock user ──────────────────────────────────────────────────────────
_MOCK_USER = MagicMock(spec=AuthenticatedUser)
_MOCK_USER.user_id = "00000000-0000-0000-0000-000000000001"
_MOCK_USER.organization_id = "00000000-0000-0000-0000-000000000002"
_MOCK_USER.email = "test@example.com"
_MOCK_USER.role = "admin"


def _get_mock_user():
    return _MOCK_USER


def _get_mock_supabase():
    return _DEFAULT_MOCK_SUPABASE


# ── Session-scoped fixture: apply global overrides ────────────────────────────
@pytest.fixture(autouse=True)
def reset_dependency_overrides():
    """
    Before each test: install the default mock overrides.
    After each test: restore to the default mocks (removing any test-specific overrides).
    This prevents state leaking between tests.
    """
    # Clear lru_cache so get_supabase() doesn't return a stale real client
    get_supabase.cache_clear()

    # Install defaults
    app.dependency_overrides[get_current_user] = _get_mock_user
    app.dependency_overrides[get_supabase] = _get_mock_supabase

    yield

    # Restore defaults after test (in case test installed its own override)
    app.dependency_overrides[get_current_user] = _get_mock_user
    app.dependency_overrides[get_supabase] = _get_mock_supabase
