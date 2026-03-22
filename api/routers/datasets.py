"""
Datasets Router — file upload URL generation, dataset management, and pipeline triggering.

Upload flow:
  1. Frontend calls POST /projects/{id}/datasets/upload-url  → gets presigned R2 PUT URL + dataset_id
  2. Frontend uploads file directly to Cloudflare R2 (never through this server)
  3. Frontend calls POST /datasets/{id}/complete-upload       → creates DB record + enqueues tiling job
  4. Tiling worker polls Supabase processing_jobs table (status='queued'), processes the file,
     and updates job status via Supabase Realtime

Storage: Cloudflare R2 (S3-compatible, zero egress fees)
Queue:   Supabase processing_jobs table (polled by workers, no separate queue service needed)
"""
from __future__ import annotations

import uuid
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from config import settings
from dependencies import get_current_user, get_supabase, AuthenticatedUser
from supabase import Client

router = APIRouter()


# ── Cloudflare R2 client (S3-compatible) ─────────────────────────────────────

def _r2_client():
    """
    Returns a boto3 S3 client configured for Cloudflare R2.
    R2 is fully S3-compatible — only the endpoint_url differs from AWS S3.
    Signature version must be 's3v4'.
    """
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",  # R2 uses 'auto' as the region
    )


# ── Request / Response models ─────────────────────────────────────────────────

class UploadRequest(BaseModel):
    filename: str
    size_bytes: int
    description: Optional[str] = None


class UploadResponse(BaseModel):
    upload_url: str
    dataset_id: str
    r2_key: str


class CompleteUploadRequest(BaseModel):
    filename: str
    size_bytes: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/datasets/upload-url",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a presigned R2 URL for direct browser upload",
)
async def request_upload_url(
    project_id: str,
    request: UploadRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Generates a presigned Cloudflare R2 PUT URL valid for 1 hour. The frontend
    uploads the file directly to R2 — the file never passes through this API server.

    Also creates a dataset record in Supabase with status='uploading' so the
    frontend can track progress immediately.
    """
    # Verify the project belongs to the user's organization
    project = (
        supabase.table("projects")
        .select("id, organization_id")
        .eq("id", project_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not project.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    dataset_id = str(uuid.uuid4())
    r2_key = f"raw/{user.organization_id}/{project_id}/{dataset_id}/{request.filename}"

    # Generate presigned R2 PUT URL (identical API to S3 presigned URLs)
    try:
        presigned_url = _r2_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.R2_BUCKET_NAME,
                "Key": r2_key,
                "ContentType": "application/octet-stream",
            },
            ExpiresIn=3600,
        )
    except ClientError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate upload URL: {e.response['Error']['Message']}",
        )

    # Create dataset record in Supabase with status='uploading'
    try:
        supabase.table("datasets").insert({
            "id": dataset_id,
            "project_id": project_id,
            "organization_id": user.organization_id,
            "name": request.filename,
            "description": request.description,
            "status": "uploading",
            "s3_raw_key": r2_key,  # column name kept for schema compatibility
            "file_size_bytes": request.size_bytes,
            "uploaded_by": user.user_id,
        }).execute()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create dataset record: {str(e)}",
        )

    return UploadResponse(upload_url=presigned_url, dataset_id=dataset_id, r2_key=r2_key)


@router.post(
    "/datasets/{dataset_id}/complete-upload",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Confirm upload completion and trigger the tiling processing pipeline",
)
async def complete_upload(
    dataset_id: str,
    request: CompleteUploadRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Called by the frontend after the R2 PUT completes.

    1. Verifies the dataset belongs to the user's organization.
    2. Updates dataset status to 'queued'.
    3. Creates a processing_jobs record with status='queued'.

    Workers poll the processing_jobs table for queued jobs and update progress
    via Supabase Realtime — no separate queue service (SQS/Queues) required.
    """
    # Fetch dataset and verify ownership
    dataset = (
        supabase.table("datasets")
        .select("id, organization_id, project_id, s3_raw_key, name")
        .eq("id", dataset_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not dataset.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    d = dataset.data
    job_id = str(uuid.uuid4())
    r2_output_key = d["s3_raw_key"].replace("/raw/", "/processed/").replace(
        d["name"], f"{dataset_id}.copc.laz"
    )

    # Update dataset status to 'queued'
    supabase.table("datasets").update({
        "status": "queued",
        "file_size_bytes": request.size_bytes,
    }).eq("id", dataset_id).execute()

    # Create processing job record — workers poll this table for status='queued'
    supabase.table("processing_jobs").insert({
        "id": job_id,
        "dataset_id": dataset_id,
        "organization_id": user.organization_id,
        "job_type": "tiling",
        "status": "queued",
        "parameters": {
            "r2_input_key": d["s3_raw_key"],
            "r2_output_key": r2_output_key,
            "r2_bucket": settings.R2_BUCKET_NAME,
            "dataset_id": dataset_id,
        },
        "created_by": user.user_id,
    }).execute()

    return {
        "dataset_id": dataset_id,
        "job_id": job_id,
        "status": "queued",
        "message": "Tiling pipeline queued. Track progress via the jobs endpoint or Supabase Realtime.",
    }


@router.get(
    "/projects/{project_id}/datasets",
    summary="List all datasets in a project",
)
async def list_datasets(
    project_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Returns all datasets for a project, ordered by creation date descending."""
    result = (
        supabase.table("datasets")
        .select("*")
        .eq("project_id", project_id)
        .eq("organization_id", user.organization_id)
        .order("created_at", desc=True)
        .execute()
    )
    return {"datasets": result.data}


@router.get(
    "/datasets/{dataset_id}",
    summary="Get a single dataset with its latest job status",
)
async def get_dataset(
    dataset_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Returns dataset metadata plus the most recent processing job."""
    dataset = (
        supabase.table("datasets")
        .select("*, processing_jobs(id, job_type, status, progress_pct, error_message, created_at, completed_at)")
        .eq("id", dataset_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not dataset.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset.data


@router.delete(
    "/datasets/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dataset and its R2 objects",
)
async def delete_dataset(
    dataset_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Deletes the dataset record from Supabase and removes the associated
    objects from Cloudflare R2 (both raw upload and processed output).
    """
    # Fetch dataset to get R2 keys before deletion
    dataset = (
        supabase.table("datasets")
        .select("id, s3_raw_key, name")
        .eq("id", dataset_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not dataset.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    d = dataset.data

    # Delete R2 objects (raw upload + processed output)
    try:
        r2 = _r2_client()
        keys_to_delete = []
        if d.get("s3_raw_key"):
            keys_to_delete.append({"Key": d["s3_raw_key"]})
            # Also attempt to delete the processed output key
            processed_key = d["s3_raw_key"].replace("/raw/", "/processed/").replace(
                d["name"], f"{dataset_id}.copc.laz"
            )
            keys_to_delete.append({"Key": processed_key})

        if keys_to_delete:
            r2.delete_objects(
                Bucket=settings.R2_BUCKET_NAME,
                Delete={"Objects": keys_to_delete, "Quiet": True},
            )
    except ClientError:
        # Log but don't fail — DB record deletion is more important
        pass

    # Delete the dataset record (cascades to processing_jobs via FK)
    result = (
        supabase.table("datasets")
        .delete()
        .eq("id", dataset_id)
        .eq("organization_id", user.organization_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
