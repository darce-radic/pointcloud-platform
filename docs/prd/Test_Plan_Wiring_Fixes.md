# Test Plan: Critical Wiring Fixes

This document outlines the comprehensive testing strategy for the three critical wiring fixes implemented in commit `8517f56`:
1. Chat streaming endpoint (`/conversations/stream`)
2. Workflow tools execution endpoint (`/workflow-tools/{tool_id}/run`)
3. Agent node library seed script (`seed_node_library.py`)

## 1. Unit Testing Strategy

Unit tests focus on isolating the business logic and mocking external dependencies (Supabase, OpenAI, n8n, LangGraph).

### 1.1 `conversations.py` Unit Tests
**File:** `api/tests/test_conversations.py`
- **Test Case 1:** `test_stream_new_conversation`
  - **Setup:** Call `/conversations/stream` without a `conversation_id`.
  - **Expectation:** Supabase `insert` is called to create a conversation. The first SSE event emitted is `{"type": "conversation_id", "conversation_id": "<uuid>"}`.
- **Test Case 2:** `test_stream_existing_conversation`
  - **Setup:** Call `/conversations/stream` with a valid `conversation_id`.
  - **Expectation:** Supabase `select` verifies the ID. No new conversation is created. History is loaded via `_load_history`.
- **Test Case 3:** `test_stream_agent_events`
  - **Setup:** Mock the LangGraph agent to yield specific events (`on_chat_model_stream`, `on_chain_start`, `on_chain_end`).
  - **Expectation:** SSE stream correctly formats tokens, stage transitions, and workflow creation events.
- **Test Case 4:** `test_save_message_called`
  - **Setup:** Complete a stream successfully.
  - **Expectation:** `_save_message` is called twice (once for user, once for assistant). Table names used must be `conversations` and `messages`.

### 1.2 `workflow_tools.py` Unit Tests
**File:** `api/tests/test_workflow_tools.py`
- **Test Case 1:** `test_run_tool_success`
  - **Setup:** Mock valid tool ownership, valid dataset ownership, and mock `httpx.AsyncClient.post`.
  - **Expectation:** Returns 200 OK with a `job_id`. Supabase `insert` into `processing_jobs` is called with status `queued`. `httpx.post` is called with the correct payload.
- **Test Case 2:** `test_run_tool_invalid_tool`
  - **Setup:** Mock Supabase to return empty data for the tool query.
  - **Expectation:** Returns 404 Not Found.
- **Test Case 3:** `test_run_tool_invalid_dataset`
  - **Setup:** Mock Supabase to return valid tool but empty data for the dataset query.
  - **Expectation:** Returns 404 Not Found.
- **Test Case 4:** `test_run_tool_n8n_timeout`
  - **Setup:** Mock `httpx.post` to raise a TimeoutException.
  - **Expectation:** Returns 200 OK (fire-and-forget logic). The `processing_jobs` row is still created.

### 1.3 `seed_node_library.py` Unit Tests
**File:** `api/tests/test_seed_node_library.py`
- **Test Case 1:** `test_make_embedding_text`
  - **Setup:** Pass a sample node dictionary.
  - **Expectation:** Returns a correctly formatted string combining name, description, and tags.
- **Test Case 2:** `test_get_embeddings_batching`
  - **Setup:** Mock OpenAI client to return dummy vectors. Pass 25 texts.
  - **Expectation:** OpenAI API is called twice (batch size 20).

## 2. Integration Testing Strategy

Integration tests verify that the API endpoints correctly interact with the actual Supabase database (using a test schema or transaction rollback) and external APIs.

**File:** `api/tests/test_integration_fixes.py`
- **Test Case 1:** `test_workflow_tools_db_integration`
  - **Setup:** Insert a dummy organization, user, dataset, and workflow_tool into the test database.
  - **Action:** Call `POST /workflow-tools/{tool_id}/run`.
  - **Expectation:** The endpoint successfully creates a row in `processing_jobs`. Query the DB to verify the row exists and has the correct metadata.
- **Test Case 2:** `test_conversations_db_integration`
  - **Setup:** Call `POST /conversations/stream` with a new message.
  - **Action:** Read the SSE stream, extract the `conversation_id`.
  - **Expectation:** Query the `conversations` and `messages` tables to verify the records were actually inserted.

## 3. End-to-End (E2E) Testing Strategy

E2E tests validate the user journey from the frontend to the backend and back.

**Framework:** Playwright (to be added to `frontend/e2e/`)
- **Test Case 1: AI Chat Stream Flow**
  - **Action:** User opens the viewer, clicks the AI Chat panel, types "Detect road markings", and presses Enter.
  - **Expectation:** A new message bubble appears. The "Understanding your request..." stage indicator appears. Text streams in token by token. The conversation persists on page reload.
- **Test Case 2: Workflow Tool Execution Flow**
  - **Action:** User clicks the "Detect Road Assets" button in the viewer toolbar.
  - **Expectation:** A toast notification appears indicating the job started. The job progress bar appears in the UI (driven by Supabase Realtime on the `processing_jobs` table).

## 4. Execution Plan

1. Write `api/tests/test_conversations.py` using `pytest` and `unittest.mock`.
2. Write `api/tests/test_workflow_tools.py`.
3. Update the existing `api/tests/test_integration.py` to include the new endpoints.
4. Run the test suite via `pytest api/tests/` to ensure all mocks pass.
5. Commit the test suite to GitHub.
