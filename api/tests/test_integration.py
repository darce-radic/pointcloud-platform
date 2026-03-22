"""
Integration tests for the PointCloud Platform API.

These tests verify the full request/response cycle for each router.
They require a running Supabase instance and valid environment variables.

Run with:
    pytest api/tests/test_integration.py -v

For CI (mocked external services):
    pytest api/tests/test_integration.py -v --mock-external
"""
from __future__ import annotations

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

# Set test environment variables before importing the app
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

from main import app  # noqa: E402

client = TestClient(app)

# ── Mock JWT token for tests ──────────────────────────────────────────────────
TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_ORG_ID = "00000000-0000-0000-0000-000000000002"
TEST_DATASET_ID = "00000000-0000-0000-0000-000000000003"

MOCK_AUTH_HEADERS = {"Authorization": "Bearer test-jwt-token"}


# ── Health check ──────────────────────────────────────────────────────────────

def test_health_check():
    """API health endpoint returns 200."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


# ── Dataset endpoints ─────────────────────────────────────────────────────────

class TestDatasetEndpoints:

    @patch("dependencies.verify_jwt_token")
    @patch("routers.datasets.get_supabase_client")
    def test_list_datasets_requires_auth(self, mock_supabase, mock_verify):
        """GET /datasets requires a valid JWT."""
        response = client.get("/datasets")
        assert response.status_code == 401

    @patch("dependencies.verify_jwt_token")
    @patch("routers.datasets.get_supabase_client")
    def test_list_datasets_returns_list(self, mock_supabase, mock_verify):
        """GET /datasets returns a list of datasets for the authenticated user."""
        mock_verify.return_value = {"sub": TEST_USER_ID, "org_id": TEST_ORG_ID}
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = []
        mock_supabase.return_value = mock_client

        response = client.get("/datasets", headers=MOCK_AUTH_HEADERS)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @patch("dependencies.verify_jwt_token")
    @patch("routers.datasets.get_supabase_client")
    @patch("routers.datasets.boto3.client")
    def test_create_upload_url(self, mock_boto, mock_supabase, mock_verify):
        """POST /datasets/upload-url returns a presigned S3 URL."""
        mock_verify.return_value = {"sub": TEST_USER_ID, "org_id": TEST_ORG_ID}

        mock_s3 = MagicMock()
        mock_s3.generate_presigned_post.return_value = {
            "url": "https://s3.amazonaws.com/test-bucket",
            "fields": {"key": "uploads/test.laz"},
        }
        mock_boto.return_value = mock_s3

        mock_client = MagicMock()
        mock_client.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": TEST_DATASET_ID, "name": "Test Dataset"}
        ]
        mock_supabase.return_value = mock_client

        response = client.post(
            "/datasets/upload-url",
            json={"filename": "test.laz", "file_size_bytes": 1024 * 1024, "project_id": None},
            headers=MOCK_AUTH_HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        assert "upload_url" in data
        assert "dataset_id" in data

    @patch("dependencies.verify_jwt_token")
    @patch("routers.datasets.get_supabase_client")
    @patch("routers.datasets.boto3.client")
    def test_complete_upload_triggers_job(self, mock_boto, mock_supabase, mock_verify):
        """POST /datasets/{id}/complete triggers a processing job."""
        mock_verify.return_value = {"sub": TEST_USER_ID, "org_id": TEST_ORG_ID}

        mock_sqs = MagicMock()
        mock_sqs.send_message.return_value = {"MessageId": "test-msg-id"}
        mock_boto.return_value = mock_sqs

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": TEST_DATASET_ID,
            "organization_id": TEST_ORG_ID,
            "s3_raw_key": f"uploads/{TEST_ORG_ID}/{TEST_DATASET_ID}/test.laz",
            "status": "uploaded",
        }
        mock_client.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "job-001"}
        ]
        mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []
        mock_supabase.return_value = mock_client

        response = client.post(
            f"/datasets/{TEST_DATASET_ID}/complete",
            json={"job_type": "tiling"},
            headers=MOCK_AUTH_HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data


# ── Conversation / AI agent endpoints ────────────────────────────────────────

class TestConversationEndpoints:

    @patch("dependencies.verify_jwt_token")
    @patch("routers.conversations.get_supabase_client")
    def test_create_conversation(self, mock_supabase, mock_verify):
        """POST /conversations creates a new conversation."""
        mock_verify.return_value = {"sub": TEST_USER_ID, "org_id": TEST_ORG_ID}
        mock_client = MagicMock()
        mock_client.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "conv-001", "title": "New Conversation"}
        ]
        mock_supabase.return_value = mock_client

        response = client.post(
            "/conversations",
            json={"dataset_id": TEST_DATASET_ID},
            headers=MOCK_AUTH_HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data

    @patch("dependencies.verify_jwt_token")
    @patch("routers.conversations.get_supabase_client")
    @patch("routers.conversations.build_workflow_agent")
    def test_send_message_streams_sse(self, mock_agent_builder, mock_supabase, mock_verify):
        """POST /conversations/{id}/messages streams SSE events."""
        mock_verify.return_value = {"sub": TEST_USER_ID, "org_id": TEST_ORG_ID}

        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": "conv-001",
            "organization_id": TEST_ORG_ID,
            "dataset_id": TEST_DATASET_ID,
        }
        mock_client.table.return_value.insert.return_value.execute.return_value.data = [{"id": "msg-001"}]
        mock_supabase.return_value = mock_client

        # Mock the agent to yield a simple event
        async def mock_stream(*args, **kwargs):
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Hello!")}}

        mock_agent = MagicMock()
        mock_agent.astream_events = mock_stream
        mock_agent_builder.return_value = mock_agent

        with client.stream(
            "POST",
            "/conversations/conv-001/messages",
            json={"content": "Extract road markings"},
            headers=MOCK_AUTH_HEADERS,
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]


# ── Job status endpoints ──────────────────────────────────────────────────────

class TestJobEndpoints:

    @patch("dependencies.verify_jwt_token")
    @patch("routers.jobs.get_supabase_client")
    def test_list_jobs(self, mock_supabase, mock_verify):
        """GET /jobs returns a list of processing jobs."""
        mock_verify.return_value = {"sub": TEST_USER_ID, "org_id": TEST_ORG_ID}
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        mock_supabase.return_value = mock_client

        response = client.get("/jobs", headers=MOCK_AUTH_HEADERS)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @patch("dependencies.verify_jwt_token")
    @patch("routers.jobs.get_supabase_client")
    def test_cancel_job(self, mock_supabase, mock_verify):
        """POST /jobs/{id}/cancel sets job status to cancelling."""
        mock_verify.return_value = {"sub": TEST_USER_ID, "org_id": TEST_ORG_ID}
        mock_client = MagicMock()
        mock_client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
            {"id": "job-001", "status": "cancelling"}
        ]
        mock_supabase.return_value = mock_client

        response = client.post("/jobs/job-001/cancel", headers=MOCK_AUTH_HEADERS)
        assert response.status_code == 200


# ── Workflow tools endpoints ──────────────────────────────────────────────────

class TestWorkflowToolEndpoints:

    @patch("dependencies.verify_jwt_token")
    @patch("routers.datasets.get_supabase_client")
    def test_list_workflow_tools(self, mock_supabase, mock_verify):
        """GET /workflow-tools returns available tools for the viewer toolbar."""
        mock_verify.return_value = {"sub": TEST_USER_ID, "org_id": TEST_ORG_ID}
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.or_.return_value.eq.return_value.execute.return_value.data = [
            {
                "id": "tool-001",
                "name": "Extract Road Assets",
                "description": "Detect road markings, signs, and drains",
                "icon": "road",
                "category": "extraction",
                "is_system_tool": True,
            }
        ]
        mock_supabase.return_value = mock_client

        response = client.get("/workflow-tools", headers=MOCK_AUTH_HEADERS)
        assert response.status_code == 200
        assert isinstance(response.json(), list)
