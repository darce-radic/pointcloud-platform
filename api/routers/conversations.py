"""
Conversations Router — AI Spatial Assistant with Server-Sent Events streaming.

Conversation flow:
  1. POST /projects/{id}/conversations          → creates a conversation record in Supabase
  2. POST /conversations/stream                 → stateless stream endpoint (frontend-facing)
     - Accepts optional conversation_id; creates one on first call and emits it as an event
     - Runs the LangGraph agent (intent → plan → nodes → generate → validate → deploy)
     - Streams tokens, stage transitions, and workflow events to the frontend
     - Persists the completed assistant message back to Supabase
  3. POST /conversations/{id}/messages          → legacy per-conversation stream (kept for compat)
  4. GET  /conversations/{id}/messages          → returns full message history
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


# ── Request models ────────────────────────────────────────────────────────────

class MessageRequest(BaseModel):
    message: str
    dataset_id: str | None = None


class StreamRequest(BaseModel):
    """Request body for the stateless /conversations/stream endpoint."""
    message: str
    dataset_id: str | None = None
    conversation_id: str | None = None   # Omit on first message; returned in stream


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_history(conv_id: str, supabase: Client) -> list:
    """Returns the last 20 messages for a conversation as LangChain message objects."""
    result = (
        supabase.table("messages")           # canonical table name
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


def _save_message(conv_id: str, role: str, content: str, metadata: dict, supabase: Client):
    supabase.table("messages").insert({     # canonical table name
        "id": str(uuid.uuid4()),
        "conversation_id": conv_id,
        "role": role,
        "content": content,
        "metadata": metadata,
    }).execute()


def _ensure_conversation(
    conversation_id: str | None,
    dataset_id: str | None,
    user: AuthenticatedUser,
    supabase: Client,
) -> tuple[str, bool]:
    """
    Returns (conv_id, is_new).
    If conversation_id is provided and valid, returns it unchanged.
    Otherwise creates a new conversation row and returns the new ID.
    """
    if conversation_id:
        row = (
            supabase.table("conversations")
            .select("id")
            .eq("id", conversation_id)
            .eq("organization_id", user.organization_id)
            .maybe_single()
            .execute()
        )
        if row.data:
            return conversation_id, False

    # Create a new conversation — attach to a project if we can find one for this dataset
    project_id: str | None = None
    if dataset_id:
        ds = (
            supabase.table("datasets")
            .select("project_id")
            .eq("id", dataset_id)
            .eq("organization_id", user.organization_id)
            .maybe_single()
            .execute()
        )
        if ds.data:
            project_id = ds.data.get("project_id")

    conv_id = str(uuid.uuid4())
    supabase.table("conversations").insert({
        "id": conv_id,
        "project_id": project_id,
        "organization_id": user.organization_id,
        "created_by": user.user_id,
        "title": "New conversation",
    }).execute()
    return conv_id, True


def _build_event_stream(
    conv_id: str,
    message: str,
    dataset_id: str | None,
    organization_id: str,
    supabase: Client,
    emit_conv_id: bool = False,
) -> AsyncGenerator[str, None]:
    """
    Shared SSE generator used by both the /stream and /{conv_id}/messages endpoints.

    SSE event types emitted:
      data: {"type": "conversation_id",  "conversation_id": "..."}  — new conv created
      data: {"type": "token",            "content": "..."}           — partial LLM token
      data: {"type": "stage",            "stage": "..."}             — agent stage label
      data: {"type": "workflow_created", "workflow_id": "..."}       — workflow deployed
      data: {"type": "job_started",      "job_id": "..."}            — processing job queued
      data: {"type": "error",            "message": "..."}           — error occurred
      data: [DONE]                                                    — stream complete
    """
    async def _gen() -> AsyncGenerator[str, None]:
        # Emit the conversation ID first so the frontend can persist it
        if emit_conv_id:
            yield f"data: {json.dumps({'type': 'conversation_id', 'conversation_id': conv_id})}\n\n"

        # Persist user message
        _save_message(conv_id, "user", message, {}, supabase)

        # Load history
        history = _load_history(conv_id, supabase)

        agent = build_workflow_agent()
        initial_state: AgentState = {
            "messages": history + [HumanMessage(content=message)],
            "intent": None,
            "planned_steps": None,
            "node_schemas": None,
            "generated_workflow": None,
            "validation_errors": None,
            "retry_count": 0,
            "deployed_workflow_id": None,
            "dataset_id": dataset_id,
            "organization_id": organization_id,
        }

        full_response: list[str] = []
        workflow_id: str | None = None

        stage_labels = {
            "intent_router":    "Understanding your request...",
            "workflow_planner": "Planning workflow steps...",
            "node_selector":    "Selecting processing nodes...",
            "json_generator":   "Generating workflow...",
            "validator":        "Validating workflow...",
            "deployer":         "Deploying to n8n...",
        }

        try:
            async for event in agent.astream_events(initial_state, version="v1"):
                event_type = event.get("event")
                event_name = event.get("name", "")

                if event_type == "on_chat_model_stream":
                    chunk = event["data"]["chunk"].content
                    if chunk:
                        full_response.append(chunk)
                        yield f"data: {json.dumps({'type': 'token', 'content': chunk})}\n\n"

                elif event_type == "on_chain_start" and event_name in stage_labels:
                    yield f"data: {json.dumps({'type': 'stage', 'stage': stage_labels[event_name]})}\n\n"

                elif event_type == "on_chain_end" and event_name == "deployer":
                    output = event["data"].get("output", {})
                    workflow_id = output.get("deployed_workflow_id")
                    if workflow_id:
                        yield f"data: {json.dumps({'type': 'workflow_created', 'workflow_id': workflow_id})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
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

    return _gen()


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
    supabase.table("conversations").insert({
        "id": conv_id,
        "project_id": project_id,
        "organization_id": user.organization_id,
        "created_by": user.user_id,
        "title": "New conversation",
    }).execute()

    return {"conversation_id": conv_id}


@router.post(
    "/conversations/stream",
    summary="Stateless SSE stream endpoint — creates conversation on first call",
)
async def stream_message(
    request: StreamRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Primary endpoint called by AiChatPanel.

    - If conversation_id is absent or invalid, a new conversation is created and its ID
      is emitted as the first SSE event so the frontend can persist it for subsequent calls.
    - All subsequent calls should include the returned conversation_id to maintain history.
    """
    conv_id, is_new = _ensure_conversation(
        request.conversation_id, request.dataset_id, user, supabase
    )
    return StreamingResponse(
        _build_event_stream(
            conv_id=conv_id,
            message=request.message,
            dataset_id=request.dataset_id,
            organization_id=user.organization_id,
            supabase=supabase,
            emit_conv_id=is_new,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disable Nginx buffering for SSE
        },
    )


@router.post(
    "/conversations/{conv_id}/messages",
    summary="Send a message to an existing conversation (streams response via SSE)",
)
async def send_message(
    conv_id: str,
    request: MessageRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Legacy per-conversation stream endpoint. Kept for backward compatibility."""
    conv = (
        supabase.table("conversations")
        .select("id, project_id")
        .eq("id", conv_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not conv.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    return StreamingResponse(
        _build_event_stream(
            conv_id=conv_id,
            message=request.message,
            dataset_id=request.dataset_id,
            organization_id=user.organization_id,
            supabase=supabase,
            emit_conv_id=False,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
        supabase.table("conversations")
        .select("id")
        .eq("id", conv_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not conv.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    result = (
        supabase.table("messages")
        .select("*")
        .eq("conversation_id", conv_id)
        .order("created_at", desc=False)
        .execute()
    )
    return {"messages": result.data}
