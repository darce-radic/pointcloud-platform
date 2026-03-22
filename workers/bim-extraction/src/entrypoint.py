"""
BIM Extraction Worker — Scan-to-BIM pipeline using Cloud2BIM + IfcOpenShell + ezdxf

Pipeline:
  1. Download LAZ/COPC from S3
  2. Pre-process with PDAL (ground removal, statistical outlier removal, voxel downsample)
  3. Run Cloud2BIM segmentation (walls, slabs, doors, windows, rooms)
  4. Generate IFC 4 file via IfcOpenShell
  5. Generate DXF floor plan via ezdxf
  6. Upload IFC + DXF to S3
  7. Update Supabase job status and dataset record

Environment variables required:
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
  AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME
  SQS_QUEUE_URL
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
import ifcopenshell
import ifcopenshell.api
import ezdxf
from ezdxf.enums import TextEntityAlignment
import numpy as np
import pdal
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bim-worker")

# ── Environment ───────────────────────────────────────────────────────────────

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET = os.environ["S3_BUCKET_NAME"]
SQS_URL = os.environ["SQS_QUEUE_URL"]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
s3 = boto3.client("s3", region_name=AWS_REGION)
sqs = boto3.client("sqs", region_name=AWS_REGION)


# ── Supabase helpers ──────────────────────────────────────────────────────────

def update_job(job_id: str, status: str, progress: int = 0, error: Optional[str] = None):
    update = {"status": status, "progress_pct": progress}
    if error:
        update["error_message"] = error
    if status == "completed":
        update["completed_at"] = "now()"
    supabase.table("processing_jobs").update(update).eq("id", job_id).execute()
    log.info(f"Job {job_id}: {status} ({progress}%)")


def is_cancelled(job_id: str) -> bool:
    result = supabase.table("processing_jobs").select("status").eq("id", job_id).single().execute()
    return result.data.get("status") == "cancelling"


# ── S3 helpers ────────────────────────────────────────────────────────────────

def download_from_s3(s3_key: str, local_path: Path):
    log.info(f"Downloading s3://{S3_BUCKET}/{s3_key} → {local_path}")
    s3.download_file(S3_BUCKET, s3_key, str(local_path))


def upload_to_s3(local_path: Path, s3_key: str) -> str:
    log.info(f"Uploading {local_path} → s3://{S3_BUCKET}/{s3_key}")
    s3.upload_file(str(local_path), S3_BUCKET, s3_key)
    return f"s3://{S3_BUCKET}/{s3_key}"


# ── PDAL pre-processing ───────────────────────────────────────────────────────

def preprocess_point_cloud(input_laz: Path, output_laz: Path) -> dict:
    """
    Pre-process the point cloud for BIM extraction:
    - Statistical outlier removal (removes noise)
    - Ground classification (SMRF algorithm)
    - Non-ground extraction (walls, ceilings, furniture)
    - Voxel downsampling to 2cm resolution for speed
    """
    pipeline_json = {
        "pipeline": [
            str(input_laz),
            {
                "type": "filters.outlier",
                "method": "statistical",
                "mean_k": 12,
                "multiplier": 2.5,
            },
            {
                "type": "filters.smrf",
                "window": 18.0,
                "slope": 0.15,
                "threshold": 0.5,
                "cell": 1.0,
            },
            {
                "type": "filters.range",
                "limits": "Classification![2:2]",  # Exclude ground (class 2)
            },
            {
                "type": "filters.voxelcenternearestneighbor",
                "cell": 0.02,  # 2cm voxel grid
            },
            {
                "type": "writers.las",
                "filename": str(output_laz),
                "compression": "laszip",
            },
        ]
    }

    pipeline = pdal.Pipeline(json.dumps(pipeline_json))
    pipeline.execute()

    metadata = pipeline.metadata
    point_count = pipeline.arrays[0].shape[0] if pipeline.arrays else 0
    log.info(f"Pre-processing complete: {point_count} points retained")
    return {"point_count": point_count}


# ── Cloud2BIM segmentation ────────────────────────────────────────────────────

def run_cloud2bim_segmentation(input_laz: Path, output_dir: Path) -> dict:
    """
    Run Cloud2BIM segmentation to detect architectural elements.

    Cloud2BIM outputs:
      - walls.json      — wall polygons with height/thickness
      - slabs.json      — floor/ceiling planes
      - openings.json   — doors and windows
      - rooms.json      — room polygons with labels
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "python3", "-m", "cloud2bim.segment",
            "--input", str(input_laz),
            "--output", str(output_dir),
            "--min-wall-height", "2.0",
            "--wall-thickness-max", "0.5",
            "--opening-detection", "true",
            "--room-labeling", "true",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Cloud2BIM segmentation failed: {result.stderr}")

    # Load segmentation results
    walls = json.loads((output_dir / "walls.json").read_text()) if (output_dir / "walls.json").exists() else []
    slabs = json.loads((output_dir / "slabs.json").read_text()) if (output_dir / "slabs.json").exists() else []
    openings = json.loads((output_dir / "openings.json").read_text()) if (output_dir / "openings.json").exists() else []
    rooms = json.loads((output_dir / "rooms.json").read_text()) if (output_dir / "rooms.json").exists() else []

    log.info(f"Segmentation: {len(walls)} walls, {len(slabs)} slabs, {len(openings)} openings, {len(rooms)} rooms")
    return {"walls": walls, "slabs": slabs, "openings": openings, "rooms": rooms}


# ── IFC generation ────────────────────────────────────────────────────────────

def generate_ifc(segments: dict, output_ifc: Path, dataset_name: str) -> Path:
    """
    Generate an IFC 4 file from Cloud2BIM segmentation results using IfcOpenShell.
    Creates a complete BIM model with walls, slabs, doors, windows, and spaces.
    """
    model = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name=dataset_name)
    ifcopenshell.api.run("unit.assign_si_units", model, length="METRE", area="SQUARE_METRE", volume="CUBIC_METRE")

    context = ifcopenshell.api.run("context.add_context", model, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", model, context_type="Model",
                                context_identifier="Body", target_view="MODEL_VIEW", parent=context)

    site = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuilding", name=dataset_name)
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Ground Floor")

    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, product=site)
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=site, product=building)
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=building, product=storey)

    # Create walls
    for i, wall_data in enumerate(segments.get("walls", [])):
        wall = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWall",
                                    name=f"Wall-{i+1:03d}")
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, product=wall)

    # Create slabs (floors/ceilings)
    for i, slab_data in enumerate(segments.get("slabs", [])):
        slab_type = "FLOOR" if slab_data.get("type") == "floor" else "ROOF"
        slab = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSlab",
                                    name=f"Slab-{i+1:03d}", predefined_type=slab_type)
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, product=slab)

    # Create doors and windows
    for i, opening in enumerate(segments.get("openings", [])):
        ifc_class = "IfcDoor" if opening.get("type") == "door" else "IfcWindow"
        element = ifcopenshell.api.run("root.create_entity", model, ifc_class=ifc_class,
                                       name=f"{opening.get('type', 'opening').capitalize()}-{i+1:03d}")
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, product=element)

    # Create spaces (rooms)
    for i, room in enumerate(segments.get("rooms", [])):
        space = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSpace",
                                     name=room.get("label", f"Room-{i+1:03d}"))
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, product=space)

    model.write(str(output_ifc))
    log.info(f"IFC written: {output_ifc}")
    return output_ifc


# ── DXF floor plan generation ─────────────────────────────────────────────────

def generate_dxf_floor_plan(segments: dict, output_dxf: Path) -> Path:
    """
    Generate a DXF floor plan from Cloud2BIM segmentation results using ezdxf.
    Creates layers for walls, doors, windows, and room labels.
    """
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    # Define layers
    doc.layers.add("WALLS", color=7)       # White
    doc.layers.add("DOORS", color=3)       # Green
    doc.layers.add("WINDOWS", color=5)     # Blue
    doc.layers.add("ROOMS", color=2)       # Yellow
    doc.layers.add("DIMENSIONS", color=1)  # Red

    # Draw walls as polylines
    for wall in segments.get("walls", []):
        pts = wall.get("polygon", [])
        if len(pts) >= 2:
            for j in range(len(pts) - 1):
                msp.add_line(
                    (pts[j][0], pts[j][1]),
                    (pts[j+1][0], pts[j+1][1]),
                    dxfattribs={"layer": "WALLS", "lineweight": 50},
                )

    # Draw door arcs
    for opening in segments.get("openings", []):
        if opening.get("type") == "door":
            cx, cy = opening.get("center", [0, 0])[:2]
            width = opening.get("width", 0.9)
            msp.add_arc(
                center=(cx, cy),
                radius=width,
                start_angle=0,
                end_angle=90,
                dxfattribs={"layer": "DOORS"},
            )
            msp.add_line(
                (cx, cy), (cx + width, cy),
                dxfattribs={"layer": "DOORS"},
            )
        elif opening.get("type") == "window":
            pts = opening.get("polygon", [])
            if len(pts) >= 2:
                msp.add_line(
                    (pts[0][0], pts[0][1]),
                    (pts[-1][0], pts[-1][1]),
                    dxfattribs={"layer": "WINDOWS", "lineweight": 25},
                )

    # Draw room labels
    for room in segments.get("rooms", []):
        cx, cy = room.get("centroid", [0, 0])[:2]
        label = room.get("label", "Room")
        area = room.get("area_m2", 0)
        msp.add_text(
            f"{label}\n{area:.1f}m²",
            dxfattribs={"layer": "ROOMS", "height": 0.2, "insert": (cx, cy)},
        )

    doc.saveas(str(output_dxf))
    log.info(f"DXF written: {output_dxf}")
    return output_dxf


# ── Main processing loop ──────────────────────────────────────────────────────

def process_message(message: dict):
    job_id = message["job_id"]
    dataset_id = message["dataset_id"]
    organization_id = message["organization_id"]
    s3_input_key = message["s3_input_key"]

    log.info(f"Starting BIM extraction: job={job_id}, dataset={dataset_id}")
    update_job(job_id, "running", 5)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        input_laz = tmp / "input.laz"
        preprocessed_laz = tmp / "preprocessed.laz"
        segments_dir = tmp / "segments"
        output_ifc = tmp / f"{dataset_id}.ifc"
        output_dxf = tmp / f"{dataset_id}.dxf"

        # Step 1: Download
        if is_cancelled(job_id): return
        download_from_s3(s3_input_key, input_laz)
        update_job(job_id, "running", 15)

        # Step 2: Pre-process
        if is_cancelled(job_id): return
        preprocess_point_cloud(input_laz, preprocessed_laz)
        update_job(job_id, "running", 35)

        # Step 3: Cloud2BIM segmentation
        if is_cancelled(job_id): return
        segments = run_cloud2bim_segmentation(preprocessed_laz, segments_dir)
        update_job(job_id, "running", 65)

        # Step 4: Generate IFC
        if is_cancelled(job_id): return
        dataset = supabase.table("datasets").select("name").eq("id", dataset_id).single().execute()
        dataset_name = dataset.data.get("name", dataset_id)
        generate_ifc(segments, output_ifc, dataset_name)
        update_job(job_id, "running", 80)

        # Step 5: Generate DXF
        generate_dxf_floor_plan(segments, output_dxf)
        update_job(job_id, "running", 90)

        # Step 6: Upload outputs to S3
        base_key = f"processed/{organization_id}/{dataset_id}"
        ifc_s3_key = f"{base_key}/{dataset_id}.ifc"
        dxf_s3_key = f"{base_key}/{dataset_id}.dxf"
        segments_s3_key = f"{base_key}/segments.json"

        upload_to_s3(output_ifc, ifc_s3_key)
        upload_to_s3(output_dxf, dxf_s3_key)

        # Upload segments JSON for viewer overlay
        segments_path = tmp / "segments.json"
        segments_path.write_text(json.dumps(segments))
        upload_to_s3(segments_path, segments_s3_key)

        # Step 7: Update Supabase
        supabase.table("datasets").update({
            "status": "completed",
            "s3_ifc_key": ifc_s3_key,
            "s3_dxf_key": dxf_s3_key,
            "s3_segments_key": segments_s3_key,
            "bim_stats": {
                "wall_count": len(segments["walls"]),
                "slab_count": len(segments["slabs"]),
                "opening_count": len(segments["openings"]),
                "room_count": len(segments["rooms"]),
            },
        }).eq("id", dataset_id).execute()

        update_job(job_id, "completed", 100)
        log.info(f"BIM extraction complete: job={job_id}")


def main():
    log.info("BIM Extraction Worker started — polling SQS")
    while True:
        response = sqs.receive_message(
            QueueUrl=SQS_URL,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            MessageAttributeNames=["job_type"],
        )

        messages = response.get("Messages", [])
        if not messages:
            continue

        for msg in messages:
            try:
                body = json.loads(msg["Body"])
                if body.get("job_type") == "bim_extraction":
                    process_message(body)
                    sqs.delete_message(QueueUrl=SQS_URL, ReceiptHandle=msg["ReceiptHandle"])
                else:
                    # Not our job type — put it back
                    sqs.change_message_visibility(
                        QueueUrl=SQS_URL,
                        ReceiptHandle=msg["ReceiptHandle"],
                        VisibilityTimeout=0,
                    )
            except Exception as e:
                log.error(f"Worker error: {e}", exc_info=True)
                update_job(body.get("job_id", "unknown"), "failed", error=str(e))


if __name__ == "__main__":
    main()
