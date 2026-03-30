import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from main import app
from dependencies import get_current_user, get_supabase

client = TestClient(app)

TEST_USER_ID = "user-123"
TEST_ORG_ID = "org-456"
MOCK_AUTH_HEADERS = {"Authorization": "Bearer mock-token"}

@pytest.fixture
def mock_verify():
    with patch("dependencies.verify_jwt_token") as mock:
        mock.return_value = {"sub": TEST_USER_ID, "org_id": TEST_ORG_ID}
        yield mock

class TestWorkflowToolsEndpoints:
    @patch("routers.workflow_tools.get_supabase")
    @patch("routers.workflow_tools.get_current_user")
    def test_list_tools(self, mock_get_user, mock_supabase):
        mock_get_user.return_value = MagicMock(user_id=TEST_USER_ID, organization_id=TEST_ORG_ID)
        
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value.data = [
            {"id": "tool-1", "name": "Test Tool"}
        ]
        mock_supabase.return_value = mock_client
        
        response = client.get("/api/v1/workflow-tools", headers=MOCK_AUTH_HEADERS)
        assert response.status_code == 200
        assert len(response.json()["tools"]) == 1

    @patch("routers.workflow_tools.httpx.AsyncClient.post")
    @patch("routers.workflow_tools.get_supabase")
    @patch("routers.workflow_tools.get_current_user")
    @pytest.mark.asyncio
    async def test_run_tool_success(self, mock_get_user, mock_supabase, mock_httpx_post):
        mock_get_user.return_value = MagicMock(user_id=TEST_USER_ID, organization_id=TEST_ORG_ID)
        
        mock_client = MagicMock()
        # Mock tool fetch
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.side_effect = [
            MagicMock(data={"id": "tool-1", "name": "Test Tool", "is_active": True, "webhook_url": "http://test"}), # Tool
            MagicMock(data={"id": "ds-1", "name": "Test DS", "copc_url": "http://copc"}) # Dataset
        ]
        mock_supabase.return_value = mock_client
        
        response = client.post(
            "/api/v1/workflow-tools/tool-1/run",
            json={"dataset_id": "ds-1", "inputs": {}},
            headers=MOCK_AUTH_HEADERS
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"
        
        # Verify insert was called
        mock_client.table.return_value.insert.assert_called_once()
