import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from main import app
from dependencies import get_current_user, get_supabase

client = TestClient(app)

TEST_USER_ID = "user-123"
TEST_ORG_ID = "org-456"
MOCK_AUTH_HEADERS = {"Authorization": "Bearer mock-token"}

class TestConversationsEndpoints:
    @patch("routers.conversations.get_supabase")
    @patch("routers.conversations.get_current_user")
    def test_create_conversation(self, mock_get_user, mock_supabase):
        mock_get_user.return_value = MagicMock(user_id=TEST_USER_ID, organization_id=TEST_ORG_ID)
        
        mock_client = MagicMock()
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {"id": "proj-1"}
        mock_supabase.return_value = mock_client
        
        response = client.post("/api/v1/projects/proj-1/conversations", headers=MOCK_AUTH_HEADERS)
        assert response.status_code == 201
        assert "conversation_id" in response.json()

    @patch("routers.conversations.get_supabase")
    @patch("routers.conversations.get_current_user")
    @patch("routers.conversations.build_workflow_agent")
    def test_stream_message_new_conv(self, mock_agent_builder, mock_get_user, mock_supabase):
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
            assert "text/event-stream" in response.headers["content-type"]
            
            # Read the first chunk to verify conversation_id is emitted
            chunks = list(response.iter_lines())
            assert any("conversation_id" in chunk for chunk in chunks)
            assert any("Hello!" in chunk for chunk in chunks)
