"""
Harmonization Worker — Point Cloud Pre-processing Pipeline
============================================================
Pipeline:
  1. Poll Supabase `processing_jobs` for status='queued' and job_type='harmonization'
  2. Claim the job atomically (status → 'processing')
  3. Download raw LAZ/LAS/E57 from Cloudflare R2
  4. Run PDAL harmonization pipeline:
       a. Statistical outlier removal (filters.outlier)
       b. Ground classification via SMRF (filters.smrf)
       c. Noise point removal (Classification == 7)
       d. Density normalization via voxel centroid (filters.voxelcentroidnearestneighbor)
       e. Coordinate reprojection to EPSG:4326 if CRS detected
  5. Upload harmonized LAZ to R2
  6. Queue a tiling job for the harmonized output
  7. Update Supabase dataset record and job status

Environment variables required:
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
  R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME
  R2_PUBLIC_BASE_URL
  POLL_INTERVAL_SECONDS  (default: 10)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config
from supabase import create_client, Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("harmonization-worker")

# ── Configuration ──────────────────────────────────────────────────────────────
SUPABASE_URL  = os.environ["SUPABASE_URL"]
SUPABASE_KEY  = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
R2_ENDPOINT   = os.environ["R2_ENDPOINT_URL"]
R2_ACCESS_KEY = os.environ["R2_ACCESS_KEY_ID"]
R2_SECRET_KEY = os.environ["R2_SECRET_ACCESS_KEY"]
R2_BUCKET     = os.environ["R2_BUCKET_NAME"]
R2_PUBLIC_BASE = os.environ.get(
    "R2_PUBLIC_BASE_URL",
    "https://pub-32e459203a854e7d92911da4f9a573c8.r2.dev",
).rstrip("/")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "10"))

# Voxel cell size in metres for density normalisation (2 cm)
VOXEL_CELL_SIZE = float(os.environ.get("VOXEL_CELL_SIZE", "0.02"))

# ── Clients ────────────────────────────────────────────────────────────────────
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
r2 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    config=Config(signature_version="s3v4"),
    region_name="auto",
)

# ── Supabase helpers ───────────────────────────────────────────────────────────
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
    if result_url:
        payload["result_url"] = result_url
    supabase.table("processing_jobs").update(payload).eq("id", job_id).execute()


def is_cancelled(job_id: str) -> bool:
    result = (
        supabase.table("processing_jobs")
        .select("status")
        .eq("id", job_id)
        .maybe_single()
        .execute()
    )
    return result.data is not None and result.data.get("status") == "cancelled"


def claim_job() -> Optional[dict]:
    result = (
        supabase.table("processing_jobs")
        .select("*, datasets(*)")
        .eq("status", "queued")
        .eq("job_type", "harmonization")
        .order("created_at")
        .limit(1)
        .execute()
    )
    if not result.data:
        return None
    job = result.data[0]
    job_id = job["id"]
    claim = (
        supabase.table("processing_jobs")
        .update({"status": "processing", "progress_pct": 1})
        .eq("id", job_id)
        .eq("status", "queued")
        .execute()
    )
    if not claim.data:
        return None
    log.info("Claimed harmonization job %s", job_id)
    return job


def queue_tiling_job(dataset_id: str, org_id: str, harmonized_key: str) -> str:
    """Queue a downstream tiling job after harmonization completes."""
    tiling_job_id = str(uuid.uuid4())
    supabase.table("processing_jobs").insert({
        "id": tiling_job_id,
        "dataset_id": dataset_id,
        "organization_id": org_id,
        "job_type": "tiling",
        "status": "queued",
        "progress_pct": 0,
        "input_key": harmonized_key,
    }).execute()
    log.info("Queued tiling job %s for dataset %s", tiling_job_id, dataset_id)
    return tiling_job_id


# ── R2 helpers ─────────────────────────────────────────────────────────────────
def download_from_r2(r2_key: str, local_path: Path) -> None:
    log.info("Downloading r2://%s/%s → %s", R2_BUCKET, r2_key, local_path)
    r2.download_file(R2_BUCKET, r2_key, str(local_path))


def upload_to_r2(local_path: Path, r2_key: str) -> str:
    log.info("Uploading %s → r2://%s/%s", local_path, R2_BUCKET, r2_key)
    r2.upload_file(
        str(local_path),
        R2_BUCKET,
        r2_key,
        ExtraArgs={"ContentType": "application/octet-stream"},
    )
    return f"{R2_PUBLIC_BASE}/{r2_key}"


# ── PDAL helpers ───────────────────────────────────────────────────────────────
def detect_reader(input_path: Path) -> str:
    ext = input_path.suffix.lower()
    return {
        ".las": "readers.las", ".laz": "readers.las",
        ".e57": "readers.e57", ".ply": "readers.ply",
        ".pts": "readers.pts", ".xyz": "readers.text",
        ".txt": "readers.text", ".csv": "readers.text",
        ".pcd": "readers.pcd",
    }.get(ext, "readers.las")


def detect_crs(input_path: Path) -> Optional[str]:
    """Use pdal info to detect the CRS of the input file."""
    try:
        result = subprocess.run(
            ["pdal", "info", "--metadata", str(input_path)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            meta = json.loads(result.stdout)
            srs = meta.get("metadata", {}).get("srs", {})
            wkt = srs.get("wkt", "")
            horizontal = srs.get("horizontal", "")
            if "EPSG:4326" in wkt or "WGS 84" in wkt:
                return "EPSG:4326"
            if horizontal and horizontal != "EPSG:0":
                return horizontal
    except Exception as exc:
        log.warning("CRS detection failed: %s", exc)
    return None


def build_harmonization_pipeline(
    input_path: Path,
    output_path: Path,
    source_crs: Optional[str] = None,
) -> dict:
    """
    Build a PDAL pipeline for point cloud harmonization:
      1. Read input (auto-detect format)
      2. Statistical outlier removal — removes isolated noise points
      3. SMRF ground classification — labels ground (Class 2) vs non-ground
      4. Remove Classification 7 (noise) points
      5. Voxel centroid nearest neighbour — density normalisation at VOXEL_CELL_SIZE
      6. Optional: reproject to EPSG:4326 if source CRS is known and differs
      7. Write harmonized LAZ output
    """
    reader_type = detect_reader(input_path)

    stages: list = [
        {
            "type": reader_type,
            "filename": str(input_path),
        },
        # Stage 1: Statistical outlier removal
        {
            "type": "filters.outlier",
            "method": "statistical",
            "mean_k": 12,
            "multiplier": 2.2,
        },
        # Stage 2: SMRF ground classification
        {
            "type": "filters.smrf",
            "window": 18.0,
            "slope": 0.15,
            "threshold": 0.5,
            "cell": 1.0,
            "ignore": "Classification[7:7]",
        },
        # Stage 3: Remove noise points (Classification 7)
        {
            "type": "filters.range",
            "limits": "Classification![7:7]",
        },
        # Stage 4: Density normalisation via voxel centroid
        {
            "type": "filters.voxelcentroidnearestneighbor",
            "cell": VOXEL_CELL_SIZE,
        },
    ]

    # Stage 5: Reproject if source CRS is known and not already EPSG:4326
    if source_crs and source_crs != "EPSG:4326":
        stages.append({
            "type": "filters.reprojection",
            "in_srs": source_crs,
            "out_srs": "EPSG:4326",
        })

    # Stage 6: Write harmonized output
    stages.append({
        "type": "writers.las",
        "filename": str(output_path),
        "compression": "laszip",
        "a_srs": "EPSG:4326" if source_crs else None,
    })

    # Remove None values from writer
    stages[-1] = {k: v for k, v in stages[-1].items() if v is not None}

    return {"pipeline": stages}


def run_pdal_harmonization(
    input_path: Path,
    output_path: Path,
    job_id: str,
) -> dict:
    """Execute the PDAL harmonization pipeline and return stats."""
    source_crs = detect_crs(input_path)
    log.info("Detected source CRS: %s", source_crs or "unknown")

    pipeline = build_harmonization_pipeline(input_path, output_path, source_crs)
    pipeline_json = json.dumps(pipeline)

    log.info("Running PDAL harmonization pipeline for job %s", job_id)
    result = subprocess.run(
        ["pdal", "pipeline", "--stdin"],
        input=pipeline_json,
        capture_output=True,
        text=True,
        timeout=7200,  # 2 hours max
    )

    if result.returncode != 0:
        error_msg = result.stderr[-3000:] if result.stderr else "PDAL pipeline failed"
        raise RuntimeError(f"PDAL harmonization error: {error_msg}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("PDAL produced no output file")

    output_size_mb = output_path.stat().st_size / 1_048_576
    log.info("PDAL harmonization complete: %.1f MB output", output_size_mb)

    # Get point count from pdal info
    point_count = 0
    try:
        info_result = subprocess.run(
            ["pdal", "info", "--summary", str(output_path)],
            capture_output=True, text=True, timeout=60,
        )
        if info_result.returncode == 0:
            summary = json.loads(info_result.stdout)
            point_count = summary.get("summary", {}).get("num_points", 0)
    except Exception:
        pass

    return {
        "point_count": point_count,
        "output_size_mb": round(output_size_mb, 2),
        "source_crs": source_crs,
        "voxel_cell_size": VOXEL_CELL_SIZE,
    }


# ── Main processing logic ──────────────────────────────────────────────────────
def process_job(job: dict) -> None:
    job_id   = job["id"]
    dataset  = job.get("datasets") or {}
    dataset_id = dataset.get("id") or job.get("dataset_id")
    org_id     = dataset.get("organization_id") or job.get("organization_id")
    raw_key    = dataset.get("s3_raw_key") or job.get("input_key")

    if not raw_key:
        raise ValueError("Job has no s3_raw_key / input_key")

    log.info(
        "Processing harmonization job %s | dataset %s | key %s",
        job_id, dataset_id, raw_key,
    )

    with tempfile.TemporaryDirectory(prefix="harmonization_") as tmpdir:
        tmp = Path(tmpdir)
        input_ext   = Path(raw_key).suffix or ".laz"
        input_path  = tmp / f"input{input_ext}"
        output_path = tmp / f"{dataset_id}_harmonized.laz"

        # Step 1: Download raw file from R2
        update_job(job_id, "processing", progress=5)
        download_from_r2(raw_key, input_path)

        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return

        # Step 2: Run PDAL harmonization pipeline
        update_job(job_id, "processing", progress=15)
        stats = run_pdal_harmonization(input_path, output_path, job_id)

        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return

        # Step 3: Upload harmonized LAZ to R2
        update_job(job_id, "processing", progress=80)
        harmonized_key = f"harmonized/{org_id}/{dataset_id}/{dataset_id}_harmonized.laz"
        harmonized_url = upload_to_r2(output_path, harmonized_key)

        # Step 4: Update dataset record with harmonization stats
        update_job(job_id, "processing", progress=90)
        supabase.table("datasets").update({
            "harmonized_key": harmonized_key,
            "point_count": stats["point_count"],
            "status": "harmonized",
        }).eq("id", dataset_id).execute()

        # Step 5: Queue downstream tiling job
        tiling_job_id = queue_tiling_job(dataset_id, org_id, harmonized_key)

        # Step 6: Mark harmonization job complete
        update_job(job_id, "completed", progress=100, result_url=harmonized_url)
        log.info(
            "Harmonization job %s complete → %d points, tiling queued as %s",
            job_id, stats["point_count"], tiling_job_id,
        )


# ── Main polling loop ──────────────────────────────────────────────────────────
def main() -> None:
    log.info(
        "Harmonization worker started | bucket=%s | poll_interval=%ds | voxel_cell=%.3fm",
        R2_BUCKET, POLL_INTERVAL, VOXEL_CELL_SIZE,
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
                        dataset = job.get("datasets") or {}
                        dataset_id = dataset.get("id") or job.get("dataset_id")
                        if dataset_id:
                            supabase.table("datasets").update(
                                {"status": "failed"}
                            ).eq("id", dataset_id).execute()
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
            time.sleep(min(POLL_INTERVAL * consecutive_errors, 120))


if __name__ == "__main__":
    main()
