"""
Conversations Router — AI Spatial Assistant with Server-Sent Events streaming.

Conversation flow:
  1. POST /projects/{id}/conversations          → creates a conversation record in Supabase
  2. POST /conversations/{id}/messages          → streams the agent response via SSE
     - Loads conversation history from Supabase
     - Runs the LangGraph agent (intent → plan → nodes → generate → validate → deploy)
     - Streams tokens to the frontend as they arrive
     - Persists the completed assistant message back to Supabase
"""
from __future__ import annotations

import json
import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage
from pydantic import BaseModel

from agent.graph import build_workflow_agent, AgentState
from dependencies import get_current_user, get_supabase, AuthenticatedUser
from supabase import Client

router = APIRouter()


class MessageRequest(BaseModel):
    message: str
    dataset_id: str | None = None


# ── Helper: load conversation history from Supabase ───────────────────────────

def _load_history(conv_id: str, supabase: Client) -> list:
    """Returns the last 20 messages for a conversation as LangChain message objects."""
    result = (
        supabase.table("ai_messages")
        .select("role, content")
        .eq("conversation_id", conv_id)
        .order("created_at", desc=False)
        .limit(20)
        .execute()
    )
    messages = []
    for row in (result.data or []):
        if row["role"] == "user":
            messages.append(HumanMessage(content=row["content"]))
        elif row["role"] == "assistant":
            messages.append(AIMessage(content=row["content"]))
    return messages


# ── Helper: persist a message to Supabase ────────────────────────────────────

def _save_message(conv_id: str, role: str, content: str, metadata: dict, supabase: Client):
    supabase.table("ai_messages").insert({
        "id": str(uuid.uuid4()),
        "conversation_id": conv_id,
        "role": role,
        "content": content,
        "metadata": metadata,
    }).execute()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/conversations",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new AI conversation session for a project",
)
async def create_conversation(
    project_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Creates a conversation record in Supabase and returns the conversation ID."""
    # Verify project ownership
    project = (
        supabase.table("projects")
        .select("id")
        .eq("id", project_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not project.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    conv_id = str(uuid.uuid4())
    supabase.table("ai_conversations").insert({
        "id": conv_id,
        "project_id": project_id,
        "organization_id": user.organization_id,
        "created_by": user.user_id,
        "title": "New conversation",
    }).execute()

    return {"conversation_id": conv_id}


@router.post(
    "/conversations/{conv_id}/messages",
    summary="Send a message to the AI assistant (streams response via SSE)",
)
async def send_message(
    conv_id: str,
    request: MessageRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Streams the AI assistant's response using Server-Sent Events.

    SSE event types emitted:
      data: {"type": "token",            "content": "..."}   — partial LLM token
      data: {"type": "stage",            "stage": "..."}     — agent stage transition
      data: {"type": "workflow_created", "workflow_id": "..."} — workflow deployed
      data: {"type": "error",            "message": "..."}   — error occurred
      data: [DONE]                                            — stream complete
    """
    # Verify conversation belongs to this user's org
    conv = (
        supabase.table("ai_conversations")
        .select("id, project_id")
        .eq("id", conv_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not conv.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Persist the user's message
    _save_message(conv_id, "user", request.message, {}, supabase)

    # Load conversation history
    history = _load_history(conv_id, supabase)

    async def event_stream() -> AsyncGenerator[str, None]:
        agent = build_workflow_agent()
        initial_state: AgentState = {
            "messages": history + [HumanMessage(content=request.message)],
            "intent": None,
            "planned_steps": None,
            "node_schemas": None,
            "generated_workflow": None,
            "validation_errors": None,
            "retry_count": 0,
            "deployed_workflow_id": None,
            "dataset_id": request.dataset_id,
            "organization_id": user.organization_id,
        }

        full_response = []
        workflow_id = None

        try:
            async for event in agent.astream_events(initial_state, version="v1"):
                event_type = event.get("event")
                event_name = event.get("name", "")

                # Stream LLM tokens to the frontend
                if event_type == "on_chat_model_stream":
                    chunk = event["data"]["chunk"].content
                    if chunk:
                        full_response.append(chunk)
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

                # Emit stage transitions so the UI can show progress indicators
                elif event_type == "on_chain_start" and event_name in (
                    "intent_router", "workflow_planner", "node_selector",
                    "json_generator", "validator", "deployer"
                ):
                    stage_labels = {
                        "intent_router": "Understanding your request...",
                        "workflow_planner": "Planning workflow steps...",
                        "node_selector": "Selecting processing nodes...",
                        "json_generator": "Generating workflow...",
                        "validator": "Validating workflow...",
                        "deployer": "Deploying to n8n...",
                    }
                    yield f"data: {json.dumps({'type': 'stage', 'stage': stage_labels.get(event_name, event_name)})}\n\n"

                # Emit workflow_created event with the deployed workflow ID
                elif event_type == "on_chain_end" and event_name == "deployer":
                    output = event["data"].get("output", {})
                    workflow_id = output.get("deployed_workflow_id")
                    if workflow_id:
                        yield f"data: {json.dumps({'type': 'workflow_created', 'workflow_id': workflow_id})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # Persist the complete assistant response to Supabase
            if full_response:
                assistant_content = "".join(full_response)
                _save_message(
                    conv_id,
                    "assistant",
                    assistant_content,
                    {"workflow_id": workflow_id} if workflow_id else {},
                    supabase,
                )
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get(
    "/conversations/{conv_id}/messages",
    summary="Get the full message history for a conversation",
)
async def get_messages(
    conv_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Returns all messages for a conversation, ordered by creation time."""
    conv = (
        supabase.table("ai_conversations")
        .select("id")
        .eq("id", conv_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not conv.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    result = (
        supabase.table("ai_messages")
        .select("*")
        .eq("conversation_id", conv_id)
        .order("created_at", desc=False)
        .execute()
    )
    return {"messages": result.data}
