"""
Datasets Router — file upload URL generation, dataset management, and pipeline triggering.

Upload flow:
  1. Frontend calls POST /projects/{id}/datasets/upload-url  → gets presigned S3 PUT URL + dataset_id
  2. Frontend uploads file directly to S3 (never through this server)
  3. Frontend calls POST /datasets/{id}/complete-upload       → creates DB record + enqueues tiling job
  4. Tiling worker picks up SQS message, processes, updates job status via Supabase Realtime
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from config import settings
from dependencies import get_current_user, get_supabase, AuthenticatedUser
from supabase import Client

router = APIRouter()

# ── AWS clients ───────────────────────────────────────────────────────────────

def _s3_client():
    return boto3.client(
        "s3",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )

def _sqs_client():
    return boto3.client(
        "sqs",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


# ── Request / Response models ─────────────────────────────────────────────────

class UploadRequest(BaseModel):
    filename: str
    size_bytes: int
    description: Optional[str] = None


class UploadResponse(BaseModel):
    upload_url: str
    dataset_id: str
    s3_key: str


class CompleteUploadRequest(BaseModel):
    filename: str
    size_bytes: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/datasets/upload-url",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a presigned S3 URL for direct browser upload",
)
async def request_upload_url(
    project_id: str,
    request: UploadRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Generates a presigned S3 PUT URL valid for 1 hour. The frontend uploads
    the file directly to S3 — the file never passes through this API server.

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
    s3_key = f"raw/{user.organization_id}/{project_id}/{dataset_id}/{request.filename}"

    # Generate presigned S3 URL
    try:
        presigned_url = _s3_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.S3_BUCKET_NAME,
                "Key": s3_key,
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
            "s3_raw_key": s3_key,
            "file_size_bytes": request.size_bytes,
            "uploaded_by": user.user_id,
        }).execute()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create dataset record: {str(e)}",
        )

    return UploadResponse(upload_url=presigned_url, dataset_id=dataset_id, s3_key=s3_key)


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
    Called by the frontend after the S3 PUT completes.

    1. Verifies the dataset belongs to the user's organization.
    2. Updates dataset status to 'queued'.
    3. Creates a processing_jobs record.
    4. Enqueues an SQS message to trigger the KEDA-scaled tiling worker.
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
    s3_output_key = d["s3_raw_key"].replace("/raw/", "/processed/").replace(
        d["name"], f"{dataset_id}.copc.laz"
    )

    # Update dataset status to 'queued'
    supabase.table("datasets").update({
        "status": "queued",
        "file_size_bytes": request.size_bytes,
    }).eq("id", dataset_id).execute()

    # Create processing job record
    supabase.table("processing_jobs").insert({
        "id": job_id,
        "dataset_id": dataset_id,
        "organization_id": user.organization_id,
        "job_type": "tiling",
        "status": "queued",
        "parameters": {
            "s3_input_key": d["s3_raw_key"],
            "s3_output_key": s3_output_key,
            "dataset_id": dataset_id,
        },
        "created_by": user.user_id,
    }).execute()

    # Enqueue SQS message — KEDA ScaledObject watches this queue and scales workers
    sqs_message = {
        "job_id": job_id,
        "dataset_id": dataset_id,
        "organization_id": user.organization_id,
        "job_type": "tiling",
        "s3_input_key": d["s3_raw_key"],
        "s3_output_key": s3_output_key,
    }
    try:
        _sqs_client().send_message(
            QueueUrl=settings.SQS_QUEUE_URL,
            MessageBody=json.dumps(sqs_message),
            MessageGroupId=user.organization_id,  # FIFO queue grouping by org
            MessageDeduplicationId=job_id,
        )
    except ClientError as e:
        # Roll back job to 'failed' status if SQS submission fails
        supabase.table("processing_jobs").update({"status": "failed", "error_message": str(e)}).eq("id", job_id).execute()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enqueue processing job: {e.response['Error']['Message']}",
        )

    return {
        "dataset_id": dataset_id,
        "job_id": job_id,
        "status": "queued",
        "message": "Tiling pipeline enqueued. Track progress via the jobs endpoint or Supabase Realtime.",
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
    summary="Delete a dataset and its S3 objects",
)
async def delete_dataset(
    dataset_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Soft-deletes the dataset record. S3 lifecycle rules handle object cleanup."""
    result = (
        supabase.table("datasets")
        .delete()
        .eq("id", dataset_id)
        .eq("organization_id", user.organization_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
