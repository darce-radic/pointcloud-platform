"""
Projects Router — project management within organizations.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from dependencies import get_current_user, get_supabase, AuthenticatedUser
from supabase import Client

router = APIRouter()


class CreateProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None
    coordinate_system: Optional[str] = "EPSG:4326"


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    coordinate_system: Optional[str] = None


@router.post(
    "/organizations/{org_id}/projects",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project within an organization",
)
async def create_project(
    org_id: str,
    request: CreateProjectRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    if user.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    project_id = str(uuid.uuid4())
    supabase.table("projects").insert({
        "id": project_id,
        "organization_id": org_id,
        "name": request.name,
        "description": request.description,
        "coordinate_system": request.coordinate_system,
        "created_by": user.user_id,
    }).execute()

    return {"project_id": project_id, "name": request.name}


@router.get(
    "/organizations/{org_id}/projects",
    summary="List all projects in an organization",
)
async def list_projects(
    org_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    if user.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = (
        supabase.table("projects")
        .select("*, datasets(count)")
        .eq("organization_id", org_id)
        .order("created_at", desc=True)
        .execute()
    )
    return {"projects": result.data}


@router.get(
    "/projects/{project_id}",
    summary="Get a single project with dataset summary",
)
async def get_project(
    project_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("projects")
        .select("*, datasets(id, name, status, created_at)")
        .eq("id", project_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return result.data


@router.patch(
    "/projects/{project_id}",
    summary="Update project metadata",
)
async def update_project(
    project_id: str,
    request: UpdateProjectRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    result = (
        supabase.table("projects")
        .update(updates)
        .eq("id", project_id)
        .eq("organization_id", user.organization_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return result.data[0]


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project and all its datasets",
)
async def delete_project(
    project_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    result = (
        supabase.table("projects")
        .delete()
        .eq("id", project_id)
        .eq("organization_id", user.organization_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
