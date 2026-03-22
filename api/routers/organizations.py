"""
Organizations Router — multi-tenant organization management.
"""
from __future__ import annotations

import uuid
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from dependencies import get_current_user, get_supabase, AuthenticatedUser
from supabase import Client

N8N_NEW_USER_WEBHOOK = "https://n8n-production-74b2f.up.railway.app/webhook/new-user-onboarding"


async def _notify_n8n(url: str, payload: dict) -> None:
    """Fire-and-forget POST to an n8n webhook."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=payload)
    except Exception:
        pass

router = APIRouter()


class CreateOrganizationRequest(BaseModel):
    name: str
    slug: str


class UpdateOrganizationRequest(BaseModel):
    name: Optional[str] = None


@router.post(
    "/organizations",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new organization and add the creator as owner",
)
async def create_organization(
    request: CreateOrganizationRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    org_id = str(uuid.uuid4())

    # Check slug uniqueness
    existing = (
        supabase.table("organizations")
        .select("id")
        .eq("slug", request.slug)
        .maybe_single()
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already taken")

    supabase.table("organizations").insert({
        "id": org_id,
        "name": request.name,
        "slug": request.slug,
        "owner_id": user.user_id,
        "subscription_tier": "free",
    }).execute()

    supabase.table("organization_members").insert({
        "organization_id": org_id,
        "user_id": user.user_id,
        "role": "owner",
    }).execute()

    # Trigger n8n onboarding workflow for the new user
    await _notify_n8n(N8N_NEW_USER_WEBHOOK, {
        "user_id": user.user_id,
        "user_email": user.email,
        "organization_id": org_id,
        "organization_name": request.name,
        "organization_slug": request.slug,
    })

    return {"organization_id": org_id, "name": request.name, "slug": request.slug}


@router.get(
    "/organizations/{org_id}",
    summary="Get organization details",
)
async def get_organization(
    org_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    if user.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = (
        supabase.table("organizations")
        .select("*, organization_members(user_id, role)")
        .eq("id", org_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return result.data


@router.patch(
    "/organizations/{org_id}",
    summary="Update organization name",
)
async def update_organization(
    org_id: str,
    request: UpdateOrganizationRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    if user.organization_id != org_id or user.role not in ("owner", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    result = supabase.table("organizations").update(updates).eq("id", org_id).execute()
    return result.data[0] if result.data else {}
