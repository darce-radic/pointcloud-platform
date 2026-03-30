"""
Workflow Tools Router — Viewer Toolbar Tool Execution

Endpoints:
  GET  /workflow-tools              → list all active tools for the authenticated org
  POST /workflow-tools/{tool_id}/run → execute a tool by triggering its n8n webhook
"""
from __future__ import annotations

import uuid
import httpx

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from supabase import Client

from dependencies import get_current_user, get_supabase, AuthenticatedUser

router = APIRouter()


# ── Request / Response models ─────────────────────────────────────────────────

class RunToolRequest(BaseModel):
    dataset_id: str
    inputs: dict = {}


class RunToolResponse(BaseModel):
    job_id: str
    status: str
    message: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/workflow-tools",
    summary="List all active viewer toolbar tools for the authenticated organisation",
)
async def list_tools(
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Returns all active workflow tools for the user's organisation, ordered by
    display_order. System tools appear before user-created tools.
    """
    result = (
        supabase.table("workflow_tools")
        .select("id, name, description, icon, webhook_url, required_inputs, is_system_tool, display_order")
        .eq("organization_id", user.organization_id)
        .eq("is_active", True)
        .order("display_order", desc=False)
        .execute()
    )
    return {"tools": result.data or []}


@router.post(
    "/workflow-tools/{tool_id}/run",
    summary="Execute a viewer toolbar tool by triggering its n8n webhook",
)
async def run_tool(
    tool_id: str,
    request: RunToolRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
) -> RunToolResponse:
    """
    Triggers the n8n webhook associated with a workflow tool and creates a
    processing_jobs row so the frontend can track progress via Supabase Realtime.

    Flow:
      1. Fetch the tool record and verify org ownership
      2. Verify the dataset belongs to this org
      3. Create a processing_jobs row (status = queued)
      4. POST to the tool's n8n webhook URL with the dataset context + inputs
      5. Return the job_id so the frontend can subscribe to job updates
    """
    # 1. Fetch and verify the tool
    tool_row = (
        supabase.table("workflow_tools")
        .select("id, name, webhook_url, is_active, organization_id")
        .eq("id", tool_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not tool_row.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool not found or does not belong to your organisation",
        )
    tool = tool_row.data
    if not tool.get("is_active"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tool is not active",
        )

    # 2. Verify dataset ownership
    dataset_row = (
        supabase.table("datasets")
        .select("id, name, copc_url, road_assets_url")
        .eq("id", request.dataset_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not dataset_row.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found or does not belong to your organisation",
        )
    dataset = dataset_row.data

    # 3. Create a processing_jobs row so the viewer can show progress
    job_id = str(uuid.uuid4())
    supabase.table("processing_jobs").insert({
        "id": job_id,
        "dataset_id": request.dataset_id,
        "organization_id": user.organization_id,
        "job_type": f"workflow_tool:{tool_id}",
        "status": "queued",
        "progress": 0,
        "metadata": {
            "tool_id": tool_id,
            "tool_name": tool["name"],
            "inputs": request.inputs,
        },
    }).execute()

    # 4. Trigger the n8n webhook (fire-and-forget; n8n updates the job via its own API)
    webhook_url = tool.get("webhook_url")
    if webhook_url:
        payload = {
            "job_id": job_id,
            "dataset_id": request.dataset_id,
            "dataset_name": dataset.get("name"),
            "copc_url": dataset.get("copc_url"),
            "road_assets_url": dataset.get("road_assets_url"),
            "organization_id": user.organization_id,
            "triggered_by": user.user_id,
            "inputs": request.inputs,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(webhook_url, json=payload)
        except httpx.HTTPError:
            # Non-fatal: the job row is already created; n8n may retry
            pass

    # 5. Return the job_id for Realtime subscription
    return RunToolResponse(
        job_id=job_id,
        status="queued",
        message=f"Tool '{tool['name']}' triggered. Track progress via job {job_id}.",
    )
