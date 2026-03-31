"""
Tests for the agent /chat endpoint (POST /api/v1/agent/chat).

Verifies:
  1. The endpoint is registered and reachable.
  2. It returns a 200 with text/event-stream content-type.
  3. The SSE stream emits token events and a [DONE] terminator.
  4. workflow_created events are forwarded when the deployer fires.
  5. Error events are forwarded when the agent raises.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# conftest.py sets env vars and imports app before this file runs
from main import app  # noqa: E402 (imported after env vars set in conftest)

client = TestClient(app)

CHAT_URL = "/api/v1/agent/chat"

VALID_PAYLOAD = {
    "message": "Classify ground points and generate a DTM",
    "organization_id": "00000000-0000-0000-0000-000000000002",
}


# ── Helper ────────────────────────────────────────────────────────────────────

def _mock_agent_stream(*events):
    """Return an async generator that yields the given event dicts."""
    async def _gen(*args, **kwargs):
        for e in events:
            yield e
    return _gen


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAgentChatEndpoint:

    @patch("agent.graph.build_workflow_agent")
    def test_endpoint_returns_200_sse(self, mock_builder):
        """POST /api/v1/agent/chat returns 200 with text/event-stream."""
        mock_agent = MagicMock()
        mock_agent.astream_events = _mock_agent_stream(
            {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Hello")}},
        )
        mock_builder.return_value = mock_agent

        with client.stream("POST", CHAT_URL, json=VALID_PAYLOAD) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]

    @patch("agent.graph.build_workflow_agent")
    def test_token_events_streamed(self, mock_builder):
        """Token chunks from the LLM are forwarded as SSE token events."""
        mock_agent = MagicMock()
        mock_agent.astream_events = _mock_agent_stream(
            {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="Clas")}},
            {"event": "on_chat_model_stream", "data": {"chunk": MagicMock(content="sify")}},
        )
        mock_builder.return_value = mock_agent

        with client.stream("POST", CHAT_URL, json=VALID_PAYLOAD) as resp:
            lines = [l for l in resp.iter_lines() if l.startswith("data: ")]

        import json
        token_contents = []
        for line in lines:
            payload = line[6:]  # strip "data: "
            if payload == "[DONE]":
                continue
            event = json.loads(payload)
            if event.get("type") == "token":
                token_contents.append(event["content"])

        assert "Clas" in token_contents
        assert "sify" in token_contents

    @patch("agent.graph.build_workflow_agent")
    def test_done_terminator_present(self, mock_builder):
        """The stream must end with 'data: [DONE]'."""
        mock_agent = MagicMock()
        mock_agent.astream_events = _mock_agent_stream()  # no events
        mock_builder.return_value = mock_agent

        with client.stream("POST", CHAT_URL, json=VALID_PAYLOAD) as resp:
            lines = list(resp.iter_lines())

        assert "data: [DONE]" in lines

    @patch("agent.graph.build_workflow_agent")
    def test_workflow_created_event_forwarded(self, mock_builder):
        """When the deployer fires, a workflow_created event is emitted."""
        mock_agent = MagicMock()
        mock_agent.astream_events = _mock_agent_stream(
            {
                "event": "on_chain_end",
                "name": "deployer",
                "data": {"output": {"deployed_workflow_id": "wf-abc123"}},
            }
        )
        mock_builder.return_value = mock_agent

        import json
        workflow_events = []
        with client.stream("POST", CHAT_URL, json=VALID_PAYLOAD) as resp:
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    continue
                event = json.loads(payload)
                if event.get("type") == "workflow_created":
                    workflow_events.append(event)

        assert len(workflow_events) == 1
        assert workflow_events[0]["workflow_id"] == "wf-abc123"

    @patch("agent.graph.build_workflow_agent")
    def test_agent_error_forwarded_as_sse_error(self, mock_builder):
        """If the agent raises, an error SSE event is emitted (not a 500)."""
        async def _failing_stream(*args, **kwargs):
            raise RuntimeError("pgvector connection refused")
            yield  # make it a generator

        mock_agent = MagicMock()
        mock_agent.astream_events = _failing_stream
        mock_builder.return_value = mock_agent

        import json
        error_events = []
        with client.stream("POST", CHAT_URL, json=VALID_PAYLOAD) as resp:
            assert resp.status_code == 200  # SSE always returns 200
            for line in resp.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload == "[DONE]":
                    continue
                event = json.loads(payload)
                if event.get("type") == "error":
                    error_events.append(event)

        assert len(error_events) == 1
        assert "pgvector connection refused" in error_events[0]["message"]

    def test_missing_organization_id_returns_422(self):
        """organization_id is required — omitting it must return 422."""
        resp = client.post(CHAT_URL, json={"message": "hello"})
        assert resp.status_code == 422

    def test_missing_message_returns_422(self):
        """message is required — omitting it must return 422."""
        resp = client.post(
            CHAT_URL,
            json={"organization_id": "00000000-0000-0000-0000-000000000002"},
        )
        assert resp.status_code == 422
