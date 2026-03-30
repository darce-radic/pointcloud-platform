"""
Integration tests for the three wiring fixes:
  1. POST /conversations/stream  — SSE endpoint
  2. POST /workflow-tools/{id}/run — tool execution endpoint

These tests use FastAPI dependency_overrides to inject mock Supabase clients
and verify the full request → DB interaction → response cycle.
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("SQS_QUEUE_URL", "http://localhost:4566/000000000000/test.fifo")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_xxx")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test")
os.environ.setdefault("N8N_API_URL", "http://localhost:5678")
os.environ.setdefault("N8N_API_KEY", "test-n8n-key")
os.environ.setdefault("APP_DOMAIN", "http://localhost:5173")
os.environ.setdefault("ENVIRONMENT", "test")

from fastapi.testclient import TestClient
from main import app  # noqa: E402
from dependencies import get_current_user, get_supabase  # noqa: E402

client = TestClient(app)

TEST_USER_ID = "user-123"
TEST_ORG_ID  = "org-456"
MOCK_AUTH_HEADERS = {"Authorization": "Bearer mock-token"}

MOCK_USER = MagicMock()
MOCK_USER.user_id = TEST_USER_ID
MOCK_USER.organization_id = TEST_ORG_ID


def _user_override():
    return MOCK_USER


class TestIntegrationFixes:

    @patch("routers.workflow_tools.httpx.AsyncClient")
    def test_workflow_tools_run_creates_job(self, mock_httpx_class):
        """
        POST /workflow-tools/{tool_id}/run creates a processing_jobs record.
        Verifies the response contains job_id and status=queued.
        """
        # Mock httpx to avoid real HTTP calls to n8n
        mock_http_instance = AsyncMock()
        mock_http_instance.__aenter__ = AsyncMock(return_value=mock_http_instance)
        mock_http_instance.__aexit__ = AsyncMock(return_value=False)
        mock_http_instance.post = AsyncMock(return_value=MagicMock(status_code=200))
        mock_httpx_class.return_value = mock_http_instance

        # Two sequential .maybe_single() calls: tool fetch, then dataset fetch
        tool_result = MagicMock()
        tool_result.data = {
            "id": "tool-1",
            "name": "Test Tool",
            "is_active": True,
            "webhook_url": "http://n8n.test/webhook/tool-1",
            "organization_id": TEST_ORG_ID,
        }
        dataset_result = MagicMock()
        dataset_result.data = {
            "id": "ds-1",
            "name": "Test DS",
            "copc_url": "http://r2.test/ds-1.copc.laz",
            "organization_id": TEST_ORG_ID,
        }

        call_count = {"n": 0}

        def table_side_effect(table_name):
            m = MagicMock()
            if table_name in ("workflow_tools", "datasets"):
                call_count["n"] += 1
                result = tool_result if call_count["n"] == 1 else dataset_result
                m.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = result
            elif table_name == "processing_jobs":
                m.insert.return_value.execute.return_value.data = [{"id": "job-new"}]
            return m

        mock_client = MagicMock()
        mock_client.table.side_effect = table_side_effect

        app.dependency_overrides[get_current_user] = _user_override
        app.dependency_overrides[get_supabase] = lambda: mock_client
        try:
            response = client.post(
                "/api/v1/workflow-tools/tool-1/run",
                json={"dataset_id": "ds-1", "inputs": {}},
                headers=MOCK_AUTH_HEADERS,
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_supabase, None)

        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data.get("status") == "queued"

    @patch("routers.conversations.build_workflow_agent")
    def test_conversations_stream_returns_sse(self, mock_agent_builder):
        """
        POST /conversations/stream returns an SSE stream with status 200.
        """
        async def mock_stream(*args, **kwargs):
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Hello!")}}

        mock_agent = MagicMock()
        mock_agent.astream_events = mock_stream
        mock_agent_builder.return_value = mock_agent

        mock_client = MagicMock()
        # _ensure_conversation: no existing conversation → creates new one
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
        mock_client.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "conv-new", "organization_id": TEST_ORG_ID}
        ]
        # History query returns empty list
        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = []

        app.dependency_overrides[get_current_user] = _user_override
        app.dependency_overrides[get_supabase] = lambda: mock_client
        try:
            with client.stream(
                "POST",
                "/api/v1/conversations/stream",
                json={"message": "Hi", "dataset_id": "ds-1"},
                headers=MOCK_AUTH_HEADERS,
            ) as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers["content-type"]
                chunks = list(response.iter_lines())
                assert len(chunks) > 0
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_supabase, None)
