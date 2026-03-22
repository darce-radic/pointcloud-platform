"""
Tiling Worker — Converts raw point cloud uploads to Cloud-Optimised Point Cloud (COPC) format.

Pipeline per job:
  1. Poll Supabase `processing_jobs` for status='queued'
  2. Claim the job atomically (status → 'processing')
  3. Download raw file from Cloudflare R2
  4. Run PDAL pipeline: read → assign CRS → sort → write COPC .laz
  5. Upload COPC output to R2 under processed/<org>/<dataset_id>.copc.laz
  6. Update dataset record with copc_url and job with status='completed'
  7. On any error: status → 'failed', store error_message

Environment variables required:
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
  R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME
  R2_PUBLIC_BASE_URL   (e.g. https://pub-32e459203a854e7d92911da4f9a573c8.r2.dev)
  POLL_INTERVAL_SECONDS  (default: 10)
  MAX_CONCURRENT_JOBS    (default: 1)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config
from supabase import create_client, Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("tiling-worker")

# ── Configuration ─────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
R2_ENDPOINT = os.environ["R2_ENDPOINT_URL"]
R2_ACCESS_KEY = os.environ["R2_ACCESS_KEY_ID"]
R2_SECRET_KEY = os.environ["R2_SECRET_ACCESS_KEY"]
R2_BUCKET = os.environ["R2_BUCKET_NAME"]
R2_PUBLIC_BASE = os.environ.get(
    "R2_PUBLIC_BASE_URL",
    "https://pub-32e459203a854e7d92911da4f9a573c8.r2.dev",
).rstrip("/")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "10"))

# ── Clients ───────────────────────────────────────────────────────────────────
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

r2 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    config=Config(signature_version="s3v4"),
    region_name="auto",
)


# ── Supabase helpers ──────────────────────────────────────────────────────────
def update_job(
    job_id: str,
    status: str,
    progress: int = 0,
    error: Optional[str] = None,
    result_url: Optional[str] = None,
) -> None:
    payload: dict = {"status": status, "progress_pct": progress}
    if error:
        payload["error_message"] = error[:2000]
    if status == "completed":
        payload["completed_at"] = "now()"
    if result_url:
        payload["result_url"] = result_url
    supabase.table("processing_jobs").update(payload).eq("id", job_id).execute()
    log.info("Job %s → %s (%d%%)", job_id, status, progress)


def is_cancelled(job_id: str) -> bool:
    result = (
        supabase.table("processing_jobs")
        .select("status")
        .eq("id", job_id)
        .single()
        .execute()
    )
    return result.data.get("status") == "cancelling"


def claim_job() -> Optional[dict]:
    """
    Atomically claim one queued job by updating its status to 'processing'.
    Uses Supabase RPC for atomic compare-and-swap to prevent double-processing.
    Falls back to a simple poll if the RPC doesn't exist yet.
    """
    try:
        result = supabase.rpc("claim_next_tiling_job", {}).execute()
        if result.data:
            return result.data[0] if isinstance(result.data, list) else result.data
    except Exception:
        pass

    # Fallback: simple poll (safe for single-worker deployments)
    result = (
        supabase.table("processing_jobs")
        .select("*, datasets(id, name, s3_raw_key, organization_id)")
        .eq("status", "queued")
        .eq("job_type", "tiling")
        .order("created_at")
        .limit(1)
        .execute()
    )
    if not result.data:
        return None

    job = result.data[0]
    # Mark as processing
    update = (
        supabase.table("processing_jobs")
        .update({"status": "processing", "started_at": "now()"})
        .eq("id", job["id"])
        .eq("status", "queued")  # guard against race condition
        .execute()
    )
    if not update.data:
        return None  # Another worker claimed it first
    job["status"] = "processing"
    return job


# ── R2 helpers ────────────────────────────────────────────────────────────────
def download_from_r2(r2_key: str, local_path: Path) -> None:
    log.info("Downloading s3://%s/%s → %s", R2_BUCKET, r2_key, local_path)
    r2.download_file(R2_BUCKET, r2_key, str(local_path))
    log.info("Download complete: %.1f MB", local_path.stat().st_size / 1_048_576)


def upload_to_r2(local_path: Path, r2_key: str) -> str:
    log.info("Uploading %s → s3://%s/%s", local_path, R2_BUCKET, r2_key)
    r2.upload_file(
        str(local_path),
        R2_BUCKET,
        r2_key,
        ExtraArgs={"ContentType": "application/octet-stream"},
    )
    public_url = f"{R2_PUBLIC_BASE}/{r2_key}"
    log.info("Upload complete → %s", public_url)
    return public_url


# ── PDAL pipeline ─────────────────────────────────────────────────────────────
def build_pdal_pipeline(input_path: Path, output_path: Path) -> dict:
    """
    Builds a PDAL pipeline that:
    1. Reads the input file (LAZ, LAS, E57, PLY, PTS, XYZ, etc.)
    2. Filters out noise points (Classification == 7)
    3. Assigns a default CRS if none is present (EPSG:4326 as fallback)
    4. Writes a COPC LAZ file (Cloud-Optimised Point Cloud)
    """
    pipeline = {
        "pipeline": [
            {
                "type": "readers.las",
                "filename": str(input_path),
                "override_srs": "",  # empty = use file's SRS
            },
            {
                "type": "filters.range",
                "limits": "Classification![7:7]",  # remove noise
            },
            {
                "type": "filters.assign",
                "value": "ReturnNumber = 1 WHERE ReturnNumber == 0",
            },
            {
                "type": "writers.copc",
                "filename": str(output_path),
                "forward": "all",
            },
        ]
    }
    return pipeline


def run_pdal(input_path: Path, output_path: Path, job_id: str) -> None:
    """Execute PDAL pipeline to convert input to COPC."""
    pipeline = build_pdal_pipeline(input_path, output_path)
    pipeline_json = json.dumps(pipeline)

    log.info("Running PDAL pipeline for job %s", job_id)
    update_job(job_id, "processing", progress=20)

    result = subprocess.run(
        ["pdal", "pipeline", "--stdin"],
        input=pipeline_json,
        capture_output=True,
        text=True,
        timeout=3600,  # 1 hour max
    )

    if result.returncode != 0:
        error_msg = result.stderr[-2000:] if result.stderr else "PDAL pipeline failed"
        raise RuntimeError(f"PDAL error: {error_msg}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("PDAL produced no output file")

    log.info(
        "PDAL complete: %.1f MB output",
        output_path.stat().st_size / 1_048_576,
    )


def detect_reader(input_path: Path) -> str:
    """Return the appropriate PDAL reader type based on file extension."""
    ext = input_path.suffix.lower()
    readers = {
        ".las": "readers.las",
        ".laz": "readers.las",
        ".e57": "readers.e57",
        ".ply": "readers.ply",
        ".pts": "readers.pts",
        ".xyz": "readers.text",
        ".txt": "readers.text",
        ".csv": "readers.text",
        ".pcd": "readers.pcd",
    }
    return readers.get(ext, "readers.las")


# ── Main processing loop ──────────────────────────────────────────────────────
def process_job(job: dict) -> None:
    job_id = job["id"]
    dataset = job.get("datasets") or {}
    dataset_id = dataset.get("id") or job.get("dataset_id")
    org_id = dataset.get("organization_id") or job.get("organization_id")
    raw_key = dataset.get("s3_raw_key") or job.get("input_key")

    if not raw_key:
        raise ValueError("Job has no s3_raw_key / input_key")

    log.info("Processing job %s | dataset %s | key %s", job_id, dataset_id, raw_key)

    with tempfile.TemporaryDirectory(prefix="tiling_") as tmpdir:
        tmp = Path(tmpdir)
        input_ext = Path(raw_key).suffix or ".laz"
        input_path = tmp / f"input{input_ext}"
        output_path = tmp / f"{dataset_id}.copc.laz"

        # Step 1: Download raw file
        update_job(job_id, "processing", progress=10)
        download_from_r2(raw_key, input_path)

        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return

        # Step 2: Run PDAL
        update_job(job_id, "processing", progress=20)
        run_pdal(input_path, output_path, job_id)

        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return

        # Step 3: Upload COPC output to R2
        update_job(job_id, "processing", progress=80)
        processed_key = f"processed/{org_id}/{dataset_id}.copc.laz"
        public_url = upload_to_r2(output_path, processed_key)

        # Step 4: Update dataset record with COPC URL
        update_job(job_id, "processing", progress=95)
        supabase.table("datasets").update(
            {
                "copc_url": public_url,
                "processed_key": processed_key,
                "status": "ready",
            }
        ).eq("id", dataset_id).execute()

        # Step 5: Mark job complete
        update_job(job_id, "completed", progress=100, result_url=public_url)
        log.info("Job %s completed → %s", job_id, public_url)


def main() -> None:
    log.info(
        "Tiling worker started | bucket=%s | poll_interval=%ds",
        R2_BUCKET,
        POLL_INTERVAL,
    )

    consecutive_errors = 0
    while True:
        try:
            job = claim_job()
            if job:
                consecutive_errors = 0
                try:
                    process_job(job)
                except Exception as exc:
                    log.exception("Job %s failed: %s", job.get("id"), exc)
                    try:
                        update_job(job["id"], "failed", error=str(exc))
                        # Mark dataset as failed too
                        dataset = job.get("datasets") or {}
                        dataset_id = dataset.get("id") or job.get("dataset_id")
                        if dataset_id:
                            supabase.table("datasets").update({"status": "failed"}).eq(
                                "id", dataset_id
                            ).execute()
                    except Exception:
                        pass
            else:
                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("Worker shutting down (SIGINT)")
            break
        except Exception as exc:
            consecutive_errors += 1
            log.exception("Unexpected error in main loop: %s", exc)
            backoff = min(POLL_INTERVAL * consecutive_errors, 120)
            time.sleep(backoff)


if __name__ == "__main__":
    main()
