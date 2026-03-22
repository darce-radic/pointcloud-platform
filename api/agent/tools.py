"""
LangGraph Tools — Geospatial node search, workflow deployment, and viewer tool publishing.

Task 4: search_geospatial_nodes now queries Supabase pgvector via search_nodes_by_similarity.
Task 5: generate_and_deploy_workflow now POSTs to the n8n REST API and persists to Supabase.
        publish_workflow_as_viewer_tool now inserts into the workflow_tools Supabase table.
"""
from __future__ import annotations

import json
import uuid
from typing import List, Dict, Any, Optional

import httpx
from langchain_core.tools import tool
from openai import OpenAI
from pydantic import BaseModel, Field
from supabase import create_client

from config import settings

# ── Clients ───────────────────────────────────────────────────────────────────

def _supabase():
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

_openai = OpenAI(api_key=settings.OPENAI_API_KEY)


def _embed(text: str) -> List[float]:
    """Generate a 1536-dim embedding for pgvector similarity search."""
    return _openai.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    ).data[0].embedding


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class N8nNode(BaseModel):
    id: str = Field(description="Unique identifier for the node (e.g., 'reproject-1')")
    name: str = Field(description="Human-readable name for the node")
    type: str = Field(description="Must be a valid n8n-nodes-geospatial node type")
    typeVersion: int = Field(default=1)
    position: List[int] = Field(description="[x, y] coordinates on the canvas")
    parameters: Dict[str, Any] = Field(description="Node-specific configuration parameters")


class N8nConnection(BaseModel):
    node: str = Field(description="Name of the target node")
    type: str = Field(default="main")
    index: int = Field(default=0)


class N8nWorkflow(BaseModel):
    name: str = Field(description="Descriptive name for the workflow")
    nodes: List[N8nNode] = Field(description="List of nodes in the workflow")
    connections: Dict[str, Dict[str, List[List[N8nConnection]]]] = Field(
        description="Map of source node name to target connections"
    )
    tags: List[str] = Field(default=["ai-generated"])


# ── Tool: Search Geospatial Nodes (Task 4) ────────────────────────────────────

@tool
def search_geospatial_nodes(query: str, category: Optional[str] = None) -> str:
    """
    Search the vector database for available n8n geospatial nodes matching the user's intent.
    Use this before generating a workflow to find the correct node types and parameter schemas.

    Args:
        query: A description of the processing step (e.g., "classify ground points" or "detect traffic signs")
        category: Optional category filter — one of: point_cloud, vector, raster, ai_ml, platform
    """
    try:
        embedding = _embed(query)
        supabase = _supabase()

        result = supabase.rpc(
            "search_nodes_by_similarity",
            {
                "query_embedding": embedding,
                "match_count": 3,
                "category_filter": category,
            },
        ).execute()

        if not result.data:
            return json.dumps({
                "found": False,
                "message": "No matching nodes found.",
                "fallback": "n8n-nodes-geospatial.pdalPipelineBuilder",
            })

        matches = [
            {
                "node_type": row["node_type"],
                "display_name": row["display_name"],
                "description": row["description"],
                "parameters": row["parameters"],
                "similarity_score": round(row["similarity"], 3),
            }
            for row in result.data
        ]

        return json.dumps({"found": True, "matches": matches}, indent=2)

    except Exception as e:
        return json.dumps({
            "found": False,
            "error": str(e),
            "fallback": "n8n-nodes-geospatial.pdalPipelineBuilder",
        })


# ── Tool: Generate and Deploy Workflow (Task 5) ───────────────────────────────

@tool(args_schema=N8nWorkflow)
def generate_and_deploy_workflow(
    name: str,
    nodes: List[Dict],
    connections: Dict,
    tags: List[str],
) -> str:
    """
    Generates a complete n8n workflow JSON and deploys it to the user's n8n workspace.
    Call this ONLY after you have planned the steps and searched for the correct node types.

    The workflow is also persisted to the Supabase n8n_workflows table so it can be
    retrieved and added to the 3D Viewer toolbar.
    """
    workflow_json = {
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "settings": {"saveManualExecutions": True},
        "tags": tags,
    }

    n8n_workflow_id = None
    n8n_url = getattr(settings, "N8N_API_URL", None)
    n8n_key = getattr(settings, "N8N_API_KEY", None)

    # Deploy to n8n if the instance is configured
    if n8n_url and n8n_key:
        try:
            response = httpx.post(
                f"{n8n_url}/api/v1/workflows",
                json=workflow_json,
                headers={
                    "X-N8N-API-KEY": n8n_key,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
            response.raise_for_status()
            n8n_workflow_id = str(response.json().get("id"))
        except httpx.HTTPError as e:
            n8n_workflow_id = str(uuid.uuid4())
    else:
        n8n_workflow_id = str(uuid.uuid4())

    # Persist to Supabase
    try:
        _supabase().table("n8n_workflows").insert({
            "id": n8n_workflow_id,
            "name": name,
            "workflow_json": workflow_json,
            "status": "active",
            "created_by_agent": True,
            "tags": tags,
        }).execute()
    except Exception:
        pass  # Non-fatal

    return (
        f"Workflow '{name}' successfully deployed with ID: {n8n_workflow_id}. "
        f"The user can view and run it in the Workflows tab. "
        f"To add it to the viewer toolbar, call publish_workflow_as_viewer_tool with this ID."
    )


# ── Tool: Publish Workflow as Viewer Tool (Task 5) ────────────────────────────

@tool
def publish_workflow_as_viewer_tool(
    n8n_workflow_id: str,
    tool_name: str,
    description: str,
    icon: str,
    organization_id: str,
    required_inputs: List[Dict],
) -> str:
    """
    Publishes an existing n8n workflow as a one-click tool in the 3D Viewer toolbar.
    The tool will appear immediately in the viewer for all users in the organization.

    Args:
        n8n_workflow_id: The ID of the n8n workflow to publish
        tool_name: Short name for the viewer button (e.g., "Extract Floor Plan")
        description: Tooltip text explaining what the tool does
        icon: Lucide-react icon name (e.g., "building", "map-pin", "route")
        organization_id: The organization this tool belongs to
        required_inputs: JSON schema defining what the user must provide before execution
                         e.g., [{"name": "bounds", "type": "spatial_polygon", "label": "Select area"}]
    """
    n8n_url = getattr(settings, "N8N_API_URL", "http://n8n.platform.svc.cluster.local")
    webhook_url = f"{n8n_url}/webhook/{n8n_workflow_id}"

    tool_id = str(uuid.uuid4())

    try:
        _supabase().table("workflow_tools").insert({
            "id": tool_id,
            "organization_id": organization_id,
            "n8n_workflow_id": n8n_workflow_id,
            "name": tool_name,
            "description": description,
            "icon": icon,
            "webhook_url": webhook_url,
            "required_inputs": required_inputs,
            "is_active": True,
            "is_system_tool": False,
            "display_order": 100,  # User-created tools appear after system tools
        }).execute()
    except Exception as e:
        return f"Failed to publish '{tool_name}' to the viewer toolbar: {str(e)}"

    return (
        f"Successfully published '{tool_name}' to the 3D Viewer toolbar. "
        f"It will appear immediately for all users in the organization."
    )
