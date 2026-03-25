# PRD-06: Agentic AI Workflow Generator

**Module:** AI Workflow Engine
**Status:** Draft
**Target Audience:** Claude Code

## 1. Overview
The platform allows users to build custom data processing pipelines (workflows) simply by chatting with an AI assistant. The AI translates the user's natural language intent into an executable n8n workflow, which is then registered as a "tool" in the 3D viewer. This PRD outlines the fixes required to connect the existing LangGraph agent to the frontend and the database.

## 2. User Stories
- As a user, I want to type "create a tool that finds all traffic signs and exports them as a CSV" into the chat panel.
- As a user, I want the AI to generate a functional processing pipeline and add a button to my 3D viewer toolbar.
- As a user, I want to click that new button in the viewer, select an area, and have the workflow execute automatically.

## 3. Architecture & Components
- **Agent Framework:** LangGraph (Python).
- **LLM:** OpenAI GPT-4o.
- **Workflow Engine:** n8n (deployed via Railway).
- **Database:** Supabase (pgvector for semantic search of n8n nodes).
- **Frontend:** React Server Server-Sent Events (SSE) for streaming chat.

## 4. Technical Specifications

### 4.1. Database Schema Additions
The agent writes to `n8n_workflows`, which does not exist in the current schema. Create it:
```sql
CREATE TABLE IF NOT EXISTS public.n8n_workflows (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  workflow_json JSONB NOT NULL,
  status TEXT DEFAULT 'active',
  created_by_agent BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### 4.2. Fix Chat Streaming Endpoint (`api/routers/conversations.py`)
The frontend calls `/api/v1/conversations/stream`, but the backend does not have this route.

**Action:** Rename the existing `POST /conversations/{conv_id}/messages` to handle the streaming correctly, or add a dedicated `/stream` endpoint.
```python
@router.post(
    "/conversations/{conv_id}/stream",
    response_class=StreamingResponse,
    summary="Stream agent response via SSE"
)
async def stream_message(conv_id: str, request: MessageRequest, ...):
    # Load history
    # Run LangGraph agent
    # Yield Server-Sent Events (SSE) tokens
```
*Note: Ensure the frontend `AiChatPanel.tsx` is updated to call the exact matching URL.*

### 4.3. Fix Workflow Execution Endpoint (`api/routers/workflow_tools.py`)
The frontend `ViewerClient.tsx` (line 507) calls `POST /api/v1/workflow-tools/{toolId}/run` when a user clicks an AI-generated tool button. This endpoint is missing.

**Action:** Create `workflow_tools.py` router.
**`POST /workflow-tools/{toolId}/run`**
- **Action:** Look up the `toolId` in the `workflow_tools` table to get the `webhook_url`.
- **Action:** Use `httpx` to send a POST request to the n8n `webhook_url`, passing the `inputs` payload (which contains the `dataset_id` and any bounding box parameters).
- **Returns:** `{ "job_id": "...", "status": "running" }`

### 4.4. Populate Agent Node Library
The agent's `node_selector` function searches `workflow_node_schemas` via pgvector. If empty, it falls back to a hardcoded string.

**Action:** Create a Python seed script (`api/scripts/seed_nodes.py`) that inserts the definitions of the platform's custom n8n nodes into the database, including their JSON schemas and embeddings.
- Node 1: `n8n-nodes-geospatial.pdalPipelineBuilder`
- Node 2: `n8n-nodes-geospatial.cloud2bim`
- Node 3: `n8n-nodes-geospatial.roadAssetExtractor`

## 5. Acceptance Criteria
- [ ] The `AiChatPanel` in the frontend successfully connects to the backend and streams the AI's response token-by-token.
- [ ] The agent successfully saves a generated workflow to the `n8n_workflows` table.
- [ ] The agent successfully registers the tool in the `workflow_tools` table, and it appears in the frontend Viewer toolbar.
- [ ] Clicking the generated tool in the frontend successfully calls `POST /workflow-tools/{toolId}/run` and triggers the corresponding n8n webhook.
