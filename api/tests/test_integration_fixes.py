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

class TestIntegrationFixes:
    @patch("routers.workflow_tools.httpx.AsyncClient.post")
    @patch("routers.workflow_tools.get_supabase")
    @patch("routers.workflow_tools.get_current_user")
    @pytest.mark.asyncio
    async def test_workflow_tools_db_integration(self, mock_get_user, mock_supabase, mock_httpx_post):
        """
        Integration test for POST /workflow-tools/{tool_id}/run.
        Verifies that the endpoint correctly interacts with the database to create a processing job.
        """
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
        
        # Verify the insert to processing_jobs was called correctly
        insert_call = mock_client.table.return_value.insert.call_args
        assert insert_call is not None
        inserted_data = insert_call[0][0]
        assert inserted_data["dataset_id"] == "ds-1"
        assert inserted_data["organization_id"] == TEST_ORG_ID
        assert inserted_data["job_type"] == "workflow_tool:tool-1"
        assert inserted_data["status"] == "queued"

    @patch("routers.conversations.get_supabase")
    @patch("routers.conversations.get_current_user")
    @patch("routers.conversations.build_workflow_agent")
    def test_conversations_db_integration(self, mock_agent_builder, mock_get_user, mock_supabase):
        """
        Integration test for POST /conversations/stream.
        Verifies that a new conversation is created and messages are saved.
        """
        mock_get_user.return_value = MagicMock(user_id=TEST_USER_ID, organization_id=TEST_ORG_ID)
        
        mock_client = MagicMock()
        # Mock dataset query for _ensure_conversation
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"project_id": "proj-1"}
        mock_supabase.return_value = mock_client
        
        async def mock_stream(*args, **kwargs):
            yield {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Hello!")}}
            
        mock_agent = MagicMock()
        mock_agent.astream_events = mock_stream
        mock_agent_builder.return_value = mock_agent
        
        with client.stream(
            "POST",
            "/api/v1/conversations/stream",
            json={"message": "Hi", "dataset_id": "ds-1"},
            headers=MOCK_AUTH_HEADERS
        ) as response:
            assert response.status_code == 200
            
            # Read chunks
            chunks = list(response.iter_lines())
            assert any("conversation_id" in chunk for chunk in chunks)
            
            # Verify _save_message was called to save user message
            # The first insert is for the conversation, the second is for the user message, the third for the assistant message
            insert_calls = mock_client.table.return_value.insert.call_args_list
            assert len(insert_calls) >= 2
