"""
Integration tests for the PointCloud Platform API.

Uses exact route paths, request schemas, and response shapes from the router implementations.

Run with:
    pytest api/tests/test_integration.py -v
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from dependencies import get_current_user, get_supabase, AuthenticatedUser

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
from dependencies import get_current_user, AuthenticatedUser  # noqa: E402

client = TestClient(app)

TEST_USER_ID    = "00000000-0000-0000-0000-000000000001"
TEST_ORG_ID     = "00000000-0000-0000-0000-000000000002"
TEST_PROJECT_ID = "00000000-0000-0000-0000-000000000004"
TEST_DATASET_ID = "00000000-0000-0000-0000-000000000003"

MOCK_AUTH_HEADERS = {"Authorization": "Bearer test-jwt-token"}

MOCK_USER = MagicMock(spec=AuthenticatedUser)
MOCK_USER.user_id = TEST_USER_ID
MOCK_USER.organization_id = TEST_ORG_ID


def _override_user():
    return MOCK_USER


# ── Health check ───────────────────────────────────────────────────────────────

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ── Dataset endpoints ──────────────────────────────────────────────────────────

class TestDatasetEndpoints:

    def test_list_datasets_requires_auth(self):
        """Without auth override, the bearer check should return 401/403/422."""
        app.dependency_overrides.pop(get_current_user, None)
        response = client.get(f"/api/v1/projects/{TEST_PROJECT_ID}/datasets")
        assert response.status_code in (401, 403, 422)

    @patch("routers.datasets.get_supabase")
    def test_list_datasets_returns_data(self, mock_supabase):
        """GET /projects/{id}/datasets returns a response with dataset data."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
            {"id": TEST_DATASET_ID, "name": "test.laz", "status": "ready"}
        ]
        mock_supabase.return_value = mock_client

        app.dependency_overrides[get_current_user] = _override_user
        try:
            response = client.get(
                f"/api/v1/projects/{TEST_PROJECT_ID}/datasets",
                headers=MOCK_AUTH_HEADERS,
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 200

    @patch("routers.datasets.get_supabase")
    @patch("routers.datasets._r2_client")
    def test_create_upload_url(self, mock_r2, mock_supabase):
        """POST /projects/{id}/datasets/upload-url returns upload_url, dataset_id, r2_key."""
        # Mock R2 presigned URL generation
        mock_r2_instance = MagicMock()
        mock_r2_instance.generate_presigned_url.return_value = "https://r2.example.com/presigned"
        mock_r2.return_value = mock_r2_instance

        mock_client = MagicMock()
        # project ownership check: .select().eq().eq().single().execute()
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": TEST_PROJECT_ID, "organization_id": TEST_ORG_ID
        }
        # dataset insert: .insert().execute()
        mock_client.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": TEST_DATASET_ID, "name": "test.laz"}
        ]
        mock_supabase.return_value = mock_client

        app.dependency_overrides[get_current_user] = _override_user
        try:
            response = client.post(
                f"/api/v1/projects/{TEST_PROJECT_ID}/datasets/upload-url",
                # UploadRequest: filename (str), size_bytes (int)
                json={"filename": "test.laz", "size_bytes": 1024 * 1024},
                headers=MOCK_AUTH_HEADERS,
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code in (200, 201)
        data = response.json()
        assert "upload_url" in data

    @patch("routers.datasets.get_supabase")
    def test_complete_upload_triggers_job(self, mock_supabase):
        """POST /datasets/{id}/complete-upload returns dataset_id and job_id."""
        # The endpoint calls table() three times:
        # 1. datasets: .select().eq().eq().maybe_single().execute()  → dataset row
        # 2. datasets: .update().eq().execute()                       → status update
        # 3. processing_jobs: .insert().execute()                     → job creation
        dataset_row = {
            "id": TEST_DATASET_ID,
            "organization_id": TEST_ORG_ID,
            "project_id": TEST_PROJECT_ID,
            "s3_raw_key": f"raw/{TEST_ORG_ID}/{TEST_PROJECT_ID}/{TEST_DATASET_ID}/test.laz",
            "name": "test.laz",
        }

        call_count = {"n": 0}

        def table_side_effect(table_name):
            call_count["n"] += 1
            m = MagicMock()
            if call_count["n"] == 1:  # datasets SELECT
                m.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = dataset_row
            elif call_count["n"] == 2:  # datasets UPDATE
                m.update.return_value.eq.return_value.execute.return_value.data = []
            else:  # processing_jobs INSERT
                m.insert.return_value.execute.return_value.data = [{"id": "job-001"}]
            return m

        mock_client = MagicMock()
        mock_client.table.side_effect = table_side_effect
        mock_supabase.return_value = mock_client

        app.dependency_overrides[get_current_user] = _override_user
        try:
            response = client.post(
                f"/api/v1/datasets/{TEST_DATASET_ID}/complete-upload",
                json={"filename": "test.laz", "size_bytes": 1024 * 1024},
                headers=MOCK_AUTH_HEADERS,
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code in (200, 202)
        data = response.json()
        assert "job_id" in data


# ── Conversation endpoints ─────────────────────────────────────────────────────

class TestConversationEndpoints:

    @patch("routers.conversations.get_supabase")
    def test_create_conversation(self, mock_supabase):
        """POST /projects/{id}/conversations creates a new conversation."""
        mock_client = MagicMock()
        mock_client.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "conv-001", "organization_id": TEST_ORG_ID}
        ]
        mock_supabase.return_value = mock_client

        app.dependency_overrides[get_current_user] = _override_user
        try:
            response = client.post(
                f"/api/v1/projects/{TEST_PROJECT_ID}/conversations",
                json={"dataset_id": TEST_DATASET_ID},
                headers=MOCK_AUTH_HEADERS,
            )
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code in (200, 201)
        data = response.json()
        assert "conversation_id" in data or "id" in data

    @patch("routers.conversations.get_supabase")
    @patch("routers.conversations.build_workflow_agent")
    def test_send_message_streams_sse(self, mock_agent_builder, mock_supabase):
        """POST /conversations/{id}/messages streams SSE. MessageRequest uses 'message' field."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "id": "conv-001",
            "organization_id": TEST_ORG_ID,
            "dataset_id": TEST_DATASET_ID,
        }
        mock_client.table.return_value.insert.return_value.execute.return_value.data = [{"id": "msg-001"}]
        # history query: .select().eq().order().execute()
        mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = []
        mock_supabase.return_value = mock_client

        async def mock_stream(*args, **kwargs):
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Hello!")}}

        mock_agent = MagicMock()
        mock_agent.astream_events = mock_stream
        mock_agent_builder.return_value = mock_agent

        app.dependency_overrides[get_current_user] = _override_user
        try:
            with client.stream(
                "POST",
                "/api/v1/conversations/conv-001/messages",
                # MessageRequest uses 'message' not 'content'
                json={"message": "Extract road markings"},
                headers=MOCK_AUTH_HEADERS,
            ) as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers["content-type"]
        finally:
            app.dependency_overrides.pop(get_current_user, None)


# ── Job endpoints ──────────────────────────────────────────────────────────────

class TestJobEndpoints:

    @patch("routers.jobs.get_supabase")
    def test_get_job(self, mock_supabase):
        """GET /jobs/{id} returns a specific job record."""
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
            "id": "job-001",
            "status": "running",
            "job_type": "tiling",
            "progress_pct": 50,
        }
        mock_supabase.return_value = mock_client

        app.dependency_overrides[get_current_user] = _override_user
        try:
            response = client.get("/api/v1/jobs/job-001", headers=MOCK_AUTH_HEADERS)
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 200

    @patch("routers.jobs.get_supabase")
    def test_cancel_job(self, mock_supabase):
        """POST /jobs/{id}/cancel sets job status to cancelling."""
        # Call 1: SELECT to fetch job row
        # Call 2: UPDATE to set status=cancelling
        call_count = {"n": 0}

        def table_side_effect(table_name):
            call_count["n"] += 1
            m = MagicMock()
            if call_count["n"] == 1:
                fetch_result = MagicMock()
                fetch_result.data = {"id": "job-001", "status": "running"}
                m.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = fetch_result
            else:
                update_result = MagicMock()
                update_result.data = [{"id": "job-001", "status": "cancelling"}]
                m.update.return_value.eq.return_value.execute.return_value = update_result
            return m

        mock_client = MagicMock()
        mock_client.table.side_effect = table_side_effect
        mock_supabase.return_value = mock_client

        app.dependency_overrides[get_current_user] = _override_user
        try:
            response = client.post("/api/v1/jobs/job-001/cancel", headers=MOCK_AUTH_HEADERS)
        finally:
            app.dependency_overrides.pop(get_current_user, None)

        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "cancelling"


# ── Workflow tools endpoints ───────────────────────────────────────────────────

class TestWorkflowToolEndpoints:
    def test_list_workflow_tools(self):
        """GET /workflow-tools returns {tools: [...]} for the authenticated org."""
        # Use dependency_overrides so the mock is injected via FastAPI DI
        # rather than patching the module-level function (which is bypassed by
        # the conftest global override).
        tools_list = [
            {
                "id": "tool-001",
                "name": "Extract Road Assets",
                "description": "Detect road markings, signs, and drains",
                "icon": "road",
                "is_system_tool": True,
                "display_order": 1,
            }
        ]
        mock_client = MagicMock()
        execute_result = MagicMock()
        execute_result.data = tools_list
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = execute_result

        app.dependency_overrides[get_supabase] = lambda: mock_client
        try:
            response = client.get("/api/v1/workflow-tools", headers=MOCK_AUTH_HEADERS)
        finally:
            app.dependency_overrides.pop(get_supabase, None)

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data
        assert isinstance(data["tools"], list)
        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "Extract Road Assets"
