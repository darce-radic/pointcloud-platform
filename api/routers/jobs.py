"""
Jobs Router — processing job status, history, and retry management.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from dependencies import get_current_user, get_supabase, AuthenticatedUser
from supabase import Client

router = APIRouter()


@router.get(
    "/jobs/{job_id}",
    summary="Get the status and progress of a specific processing job",
)
async def get_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Returns full job details including progress percentage and any error messages."""
    result = (
        supabase.table("processing_jobs")
        .select("*")
        .eq("id", job_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return result.data


@router.get(
    "/datasets/{dataset_id}/jobs",
    summary="List all processing jobs for a dataset",
)
async def list_dataset_jobs(
    dataset_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Returns all jobs for a dataset, ordered by creation date descending."""
    result = (
        supabase.table("processing_jobs")
        .select("*")
        .eq("dataset_id", dataset_id)
        .eq("organization_id", user.organization_id)
        .order("created_at", desc=True)
        .execute()
    )
    return {"jobs": result.data}


@router.post(
    "/jobs/{job_id}/cancel",
    summary="Request cancellation of a queued or running job",
)
async def cancel_job(
    job_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Marks a job as 'cancelling'. The worker polls this status and exits cleanly.
    Jobs that are already completed or failed cannot be cancelled.
    """
    job = (
        supabase.table("processing_jobs")
        .select("id, status")
        .eq("id", job_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not job.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if job.data["status"] in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel a job with status '{job.data['status']}'",
        )

    supabase.table("processing_jobs").update({"status": "cancelling"}).eq("id", job_id).execute()
    return {"job_id": job_id, "status": "cancelling"}
