"""
Shared FastAPI dependencies — Supabase client, auth, and tenant resolution.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from config import settings

# ── Supabase client (service-role, server-side only) ─────────────────────────

@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Return a cached Supabase service-role client.
    Uses the service-role key so the API can bypass RLS where needed.
    All user-facing queries still enforce RLS via the anon key in the frontend.
    """
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


# ── Bearer token extraction ───────────────────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)


class AuthenticatedUser:
    """Resolved user context extracted from the Supabase JWT."""
    def __init__(self, user_id: str, organization_id: str, email: str, role: str):
        self.user_id = user_id
        self.organization_id = organization_id
        self.email = email
        self.role = role


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    supabase: Client = Depends(get_supabase),
) -> AuthenticatedUser:
    """
    Validates the Supabase JWT from the Authorization header and resolves
    the user's organization_id and role from the profiles table.

    Raises HTTP 401 if the token is missing or invalid.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        # Verify the JWT against Supabase auth
        user_response = supabase.auth.get_user(token)
        if not user_response or not user_response.user:
            raise ValueError("Invalid token")
        user = user_response.user
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Resolve organization membership and role
    try:
        membership = (
            supabase.table("organization_members")
            .select("organization_id, role")
            .eq("user_id", user.id)
            .limit(1)
            .single()
            .execute()
        )
        org_id = membership.data["organization_id"]
        role = membership.data["role"]
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not a member of any organization",
        )

    return AuthenticatedUser(
        user_id=user.id,
        organization_id=org_id,
        email=user.email or "",
        role=role,
    )
