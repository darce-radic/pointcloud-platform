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


@router.post(
    "/datasets/{dataset_id}/bim-extraction",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger BIM extraction (IFC + DXF floor plan) for a dataset",
)
async def trigger_bim_extraction(
    dataset_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Queues a bim_extraction job for the given dataset.

    The BIM extraction worker polls `processing_jobs` for job_type='bim_extraction'
    and produces:
      - An IFC 4 file (walls, slabs, doors, windows, spaces)
      - A DXF floor plan (layered: WALLS, DOORS, WINDOWS, ROOMS)
      - A segments JSON for viewer overlay

    Both files are uploaded to R2 and the dataset record is updated with their URLs.
    """
    # Verify dataset belongs to user's organization and is ready
    dataset = (
        supabase.table("datasets")
        .select("id, organization_id, s3_raw_key, name, status")
        .eq("id", dataset_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not dataset.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    d = dataset.data
    if d.get("status") not in ("ready", "completed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dataset must be in 'ready' or 'completed' state to run BIM extraction (current: {d.get('status')})",
        )

    raw_key = d.get("s3_raw_key")
    if not raw_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset has no source file")

    job_id = str(uuid.uuid4())

    # Create processing job record
    supabase.table("processing_jobs").insert({
        "id": job_id,
        "dataset_id": dataset_id,
        "organization_id": user.organization_id,
        "job_type": "bim_extraction",
        "status": "queued",
        "parameters": {
            "r2_input_key": raw_key,
            "dataset_id": dataset_id,
        },
        "created_by": user.user_id,
    }).execute()

    return {
        "dataset_id": dataset_id,
        "job_id": job_id,
        "status": "queued",
        "message": "BIM extraction queued. The worker will produce IFC and DXF outputs.",
    }


@router.post(
    "/datasets/{dataset_id}/road-assets",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger road asset extraction (GeoJSON) for a dataset",
)
async def trigger_road_assets(
    dataset_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Queues a road_asset_extraction job for the given dataset.

    The road assets worker polls `processing_jobs` for job_type='road_asset_extraction'
    and produces a GeoJSON FeatureCollection containing:
      - Road markings (lane lines, arrows, symbols)
      - Traffic signs
      - Drains and manholes

    The GeoJSON is uploaded to R2 and the dataset record is updated with its URL.
    """
    # Verify dataset belongs to user's organization and is ready
    dataset = (
        supabase.table("datasets")
        .select("id, organization_id, s3_raw_key, name, status")
        .eq("id", dataset_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not dataset.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    d = dataset.data
    if d.get("status") not in ("ready", "completed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dataset must be in 'ready' or 'completed' state to run road asset extraction (current: {d.get('status')})",
        )

    raw_key = d.get("s3_raw_key")
    if not raw_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset has no source file")

    job_id = str(uuid.uuid4())

    # Create processing job record
    supabase.table("processing_jobs").insert({
        "id": job_id,
        "dataset_id": dataset_id,
        "organization_id": user.organization_id,
        "job_type": "road_asset_extraction",
        "status": "queued",
        "parameters": {
            "r2_input_key": raw_key,
            "dataset_id": dataset_id,
        },
        "created_by": user.user_id,
    }).execute()

    return {
        "dataset_id": dataset_id,
        "job_id": job_id,
        "status": "queued",
        "message": "Road asset extraction queued. The worker will produce a GeoJSON output.",
    }


# ── Panoramic Image Endpoints ─────────────────────────────────────────────────

@router.get(
    "/datasets/{dataset_id}/images/nearest",
    summary="Get the nearest panoramic image to a lat/lon coordinate",
)
async def get_nearest_panoramic_image(
    dataset_id: str,
    lat: float,
    lon: float,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Returns the nearest panoramic image to the given lat/lon coordinates.
    Uses PostGIS ST_Distance for spatial proximity search.

    Query params:
      lat: WGS84 latitude
      lon: WGS84 longitude

    Returns:
      { id, image_url, thumbnail_url, lat, lon, heading_deg, captured_at, sequence_index }
    """
    dataset = (
        supabase.table("datasets")
        .select("id, organization_id")
        .eq("id", dataset_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not dataset.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    # Use PostGIS RPC to find nearest image
    result = supabase.rpc(
        "get_nearest_panoramic_image",
        {
            "p_dataset_id": dataset_id,
            "p_lat": lat,
            "p_lon": lon,
            "p_limit": 1,
        },
    ).execute()

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No panoramic images found for this dataset",
        )

    img = result.data[0]
    return {
        "id": img.get("id"),
        "image_url": img.get("image_url"),
        "thumbnail_url": img.get("thumbnail_url"),
        "lat": img.get("lat"),
        "lon": img.get("lon"),
        "heading_deg": img.get("heading_deg"),
        "captured_at": img.get("captured_at"),
        "sequence_index": img.get("sequence_index"),
    }


@router.get(
    "/datasets/{dataset_id}/images",
    summary="List panoramic images for a dataset (for trajectory rendering)",
)
async def list_panoramic_images(
    dataset_id: str,
    limit: int = 200,
    offset: int = 0,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """
    Returns a paginated list of panoramic images for a dataset.
    Used to render the trajectory line on the 2D map panel.
    """
    dataset = (
        supabase.table("datasets")
        .select("id, organization_id")
        .eq("id", dataset_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not dataset.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    result = (
        supabase.table("panoramic_images")
        .select("id, image_url, thumbnail_url, lat, lon, heading_deg, captured_at, sequence_index")
        .eq("dataset_id", dataset_id)
        .order("sequence_index")
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {
        "dataset_id": dataset_id,
        "total": len(result.data),
        "offset": offset,
        "limit": limit,
        "images": result.data or [],
    }
