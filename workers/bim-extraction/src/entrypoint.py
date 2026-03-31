"""
BIM Extraction Worker — Scan-to-BIM pipeline using Cloud2BIM + IfcOpenShell + ezdxf

Pipeline:
  1. Poll Supabase `processing_jobs` for status='queued' and job_type='bim_extraction'
  2. Claim the job atomically (status → 'processing')
  3. Download LAZ/COPC from Cloudflare R2
  4. Pre-process with PDAL (ground removal, statistical outlier removal, voxel downsample)
  5. Run Cloud2BIM segmentation (walls, slabs, doors, windows, rooms)
  6. Generate IFC 4 file via IfcOpenShell
  7. Generate DXF floor plan via ezdxf
  8. Upload IFC + DXF + segments JSON to R2
  9. Update Supabase job status and dataset record

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
import ifcopenshell
import ifcopenshell.api
import ezdxf
import numpy as np
import pdal
from supabase import create_client, Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("bim-worker")

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
    Atomically claim one queued bim_extraction job.
    Falls back to a simple poll for single-worker deployments.
    """
    result = (
        supabase.table("processing_jobs")
        .select("*, datasets(id, name, s3_raw_key, organization_id)")
        .eq("status", "queued")
        .eq("job_type", "bim_extraction")
        .order("created_at")
        .limit(1)
        .execute()
    )
    if not result.data:
        return None

    job = result.data[0]
    job_id = job["id"]

    # Atomically claim: only update if still 'queued'
    claim = (
        supabase.table("processing_jobs")
        .update({"status": "processing", "progress_pct": 1})
        .eq("id", job_id)
        .eq("status", "queued")
        .execute()
    )
    if not claim.data:
        return None  # Another worker claimed it first

    log.info("Claimed job %s", job_id)
    return job


# ── R2 helpers ────────────────────────────────────────────────────────────────

def download_from_r2(r2_key: str, local_path: Path) -> None:
    log.info("Downloading r2://%s/%s → %s", R2_BUCKET, r2_key, local_path)
    r2.download_file(R2_BUCKET, r2_key, str(local_path))


def upload_to_r2(local_path: Path, r2_key: str, content_type: str = "application/octet-stream") -> str:
    log.info("Uploading %s → r2://%s/%s", local_path, R2_BUCKET, r2_key)
    r2.upload_file(
        str(local_path),
        R2_BUCKET,
        r2_key,
        ExtraArgs={"ContentType": content_type},
    )
    return f"{R2_PUBLIC_BASE}/{r2_key}"


# ── PDAL pre-processing ───────────────────────────────────────────────────────

def preprocess_point_cloud(input_laz: Path, output_laz: Path) -> dict:
    """
    Pre-process the point cloud for BIM extraction:
    - Statistical outlier removal
    - Ground classification (SMRF)
    - Non-ground extraction (walls, ceilings, furniture)
    - Voxel downsampling to 2cm resolution
    """
    pipeline_json = {
        "pipeline": [
            str(input_laz),
            {"type": "filters.outlier", "method": "statistical", "mean_k": 12, "multiplier": 2.5},
            {"type": "filters.smrf", "window": 18.0, "slope": 0.15, "threshold": 0.5, "cell": 1.0},
            {"type": "filters.range", "limits": "Classification![2:2]"},
            {"type": "filters.voxelcenternearestneighbor", "cell": 0.02},
            {"type": "writers.las", "filename": str(output_laz), "compression": "laszip"},
        ]
    }
    pipeline = pdal.Pipeline(json.dumps(pipeline_json))
    pipeline.execute()
    point_count = pipeline.arrays[0].shape[0] if pipeline.arrays else 0
    log.info("Pre-processing complete: %d points retained", point_count)
    return {"point_count": point_count}


# ── Cloud2BIM segmentation ────────────────────────────────────────────────────

def run_cloud2bim_segmentation(input_laz: Path, output_dir: Path) -> dict:
    """
    Run Cloud2BIM segmentation to detect architectural elements.
    Falls back to a heuristic segmentation if Cloud2BIM is not installed.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Try Cloud2BIM first
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

    if result.returncode == 0:
        walls = json.loads((output_dir / "walls.json").read_text()) if (output_dir / "walls.json").exists() else []
        slabs = json.loads((output_dir / "slabs.json").read_text()) if (output_dir / "slabs.json").exists() else []
        openings = json.loads((output_dir / "openings.json").read_text()) if (output_dir / "openings.json").exists() else []
        rooms = json.loads((output_dir / "rooms.json").read_text()) if (output_dir / "rooms.json").exists() else []
        log.info("Cloud2BIM: %d walls, %d slabs, %d openings, %d rooms", len(walls), len(slabs), len(openings), len(rooms))
        return {"walls": walls, "slabs": slabs, "openings": openings, "rooms": rooms}

    # Fallback: PDAL-based heuristic segmentation
    log.warning("Cloud2BIM not available (%s), using PDAL heuristic fallback", result.stderr[:200])
    return _heuristic_segmentation(input_laz)


def _heuristic_segmentation(input_laz: Path) -> dict:
    """
    Heuristic wall/floor/ceiling detection using PDAL + iterative RANSAC plane fitting.

    Algorithm:
      1. Load the point cloud and strip points outside the interior Z range.
      2. Iteratively fit planes using RANSAC (via PDAL filters.normal +
         manual RANSAC on normal vectors) until fewer than MIN_REMAINING
         points remain or MAX_PLANES iterations are exhausted.
      3. Classify each plane as:
           - floor  : normal ≈ (0,0,1)  and  Z_centroid ≈ Z_min
           - ceiling: normal ≈ (0,0,1)  and  Z_centroid ≈ Z_max
           - wall   : normal ≈ horizontal (|nz| < WALL_NORMAL_Z_THRESH)
      4. For each wall plane extract the 2-D convex-hull footprint.
      5. Derive room polygons from the convex hull of all inlier XY points.
    """
    RANSAC_ITERATIONS = 200          # per plane
    RANSAC_DIST_THRESH = 0.08        # metres — point-to-plane inlier distance
    MIN_INLIER_FRACTION = 0.03       # plane must explain ≥ 3 % of remaining pts
    MAX_PLANES = 20
    WALL_NORMAL_Z_THRESH = 0.25      # |nz| < this → wall
    HORIZ_NORMAL_Z_THRESH = 0.90     # |nz| > this → floor/ceiling
    MIN_REMAINING = 500              # stop when fewer points remain

    try:
        # ── Step 1: load & filter ────────────────────────────────────────────
        pipeline_json = {
            "pipeline": [
                str(input_laz),
                # Keep interior height band (skip underground / sky noise)
                {"type": "filters.range", "limits": "Z[-0.5:5.0]"},
                # Voxel downsample to ≤ 500 k pts for speed
                {"type": "filters.voxelcentroidnearestneighbor", "cell": 0.05},
                # Estimate normals (k=20 neighbours)
                {"type": "filters.normal", "knn": 20},
            ]
        }
        pipeline = pdal.Pipeline(json.dumps(pipeline_json))
        pipeline.execute()
        if not pipeline.arrays or len(pipeline.arrays[0]) == 0:
            return {"walls": [], "slabs": [], "openings": [], "rooms": []}

        arr = pipeline.arrays[0]
        pts = np.column_stack([arr["X"], arr["Y"], arr["Z"]]).astype(np.float64)
        normals = np.column_stack([arr["NormalX"], arr["NormalY"], arr["NormalZ"]]).astype(np.float64)

        x_min, x_max = float(pts[:, 0].min()), float(pts[:, 0].max())
        y_min, y_max = float(pts[:, 1].min()), float(pts[:, 1].max())
        z_min, z_max = float(pts[:, 2].min()), float(pts[:, 2].max())

        # ── Step 2: iterative RANSAC plane fitting ───────────────────────────
        rng = np.random.default_rng(seed=42)
        remaining_mask = np.ones(len(pts), dtype=bool)
        planes: list[dict] = []

        for _ in range(MAX_PLANES):
            remaining_idx = np.where(remaining_mask)[0]
            if len(remaining_idx) < MIN_REMAINING:
                break

            best_inliers: np.ndarray = np.array([], dtype=int)
            best_normal: np.ndarray = np.zeros(3)
            best_d: float = 0.0

            for _ in range(RANSAC_ITERATIONS):
                # Sample 3 random points
                sample_idx = rng.choice(remaining_idx, size=3, replace=False)
                p0, p1, p2 = pts[sample_idx]
                n = np.cross(p1 - p0, p2 - p0)
                norm_len = np.linalg.norm(n)
                if norm_len < 1e-9:
                    continue
                n = n / norm_len
                d = -float(np.dot(n, p0))

                # Point-to-plane distance for all remaining points
                dists = np.abs(pts[remaining_idx] @ n + d)
                inlier_local = np.where(dists < RANSAC_DIST_THRESH)[0]

                if len(inlier_local) > len(best_inliers):
                    best_inliers = remaining_idx[inlier_local]
                    best_normal = n
                    best_d = d

            if len(best_inliers) < MIN_INLIER_FRACTION * len(remaining_idx):
                break  # No significant plane found

            # Refine normal via SVD on inlier points
            inlier_pts = pts[best_inliers]
            centroid = inlier_pts.mean(axis=0)
            _, _, Vt = np.linalg.svd(inlier_pts - centroid)
            refined_n = Vt[-1]  # Smallest singular vector = plane normal
            if refined_n[2] < 0:
                refined_n = -refined_n  # Orient upward / outward

            planes.append({
                "normal": refined_n,
                "centroid": centroid,
                "inlier_idx": best_inliers,
                "inlier_pts": inlier_pts,
            })
            remaining_mask[best_inliers] = False

        # ── Step 3: classify planes ──────────────────────────────────────────
        walls: list[dict] = []
        slabs: list[dict] = []

        for plane in planes:
            n = plane["normal"]
            c = plane["centroid"]
            ipts = plane["inlier_pts"]
            nz = abs(float(n[2]))

            if nz > HORIZ_NORMAL_Z_THRESH:
                # Horizontal plane → floor or ceiling
                slab_type = "floor" if float(c[2]) < (z_min + z_max) / 2 else "ceiling"
                # Convex hull footprint
                hull_pts = _convex_hull_2d(ipts[:, :2])
                slabs.append({
                    "type": slab_type,
                    "z": float(c[2]),
                    "polygon": hull_pts,
                    "area_m2": float(_polygon_area(hull_pts)),
                })

            elif nz < WALL_NORMAL_Z_THRESH:
                # Vertical plane → wall
                # Project inlier points onto the wall plane's local 2-D axes
                # and extract the bounding segment (start/end of wall run)
                up = np.array([0.0, 0.0, 1.0])
                along = np.cross(n, up)
                along_len = np.linalg.norm(along)
                if along_len < 1e-9:
                    continue
                along = along / along_len
                proj = (ipts - c) @ along
                p_start = c + float(proj.min()) * along
                p_end   = c + float(proj.max()) * along
                wall_height = float(ipts[:, 2].max() - ipts[:, 2].min())
                walls.append({
                    "polygon": [
                        [float(p_start[0]), float(p_start[1])],
                        [float(p_end[0]),   float(p_end[1])],
                    ],
                    "height": max(wall_height, 0.5),
                    "thickness": 0.2,
                    "normal": [float(n[0]), float(n[1])],
                })

        # ── Step 4: room polygon from all inlier XY hull ─────────────────────
        all_inlier_xy = np.vstack([p["inlier_pts"][:, :2] for p in planes]) if planes else pts[:, :2]
        room_hull = _convex_hull_2d(all_inlier_xy)
        cx = float(np.mean([p[0] for p in room_hull]))
        cy = float(np.mean([p[1] for p in room_hull]))
        rooms = [{
            "label": "Room",
            "centroid": [cx, cy],
            "area_m2": float(_polygon_area(room_hull)),
            "polygon": room_hull,
        }]

        # Ensure at least a floor slab exists
        if not any(s["type"] == "floor" for s in slabs):
            slabs.insert(0, {
                "type": "floor",
                "z": z_min,
                "polygon": [[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max]],
                "area_m2": (x_max - x_min) * (y_max - y_min),
            })

        log.info(
            "RANSAC segmentation: %d walls, %d slabs, 0 openings, %d rooms",
            len(walls), len(slabs), len(rooms),
        )
        return {"walls": walls, "slabs": slabs, "openings": [], "rooms": rooms}

    except Exception as e:
        log.warning("RANSAC segmentation failed (%s), using bbox fallback", e)
        # Last-resort bounding-box fallback
        try:
            pipeline_json = {"pipeline": [str(input_laz), {"type": "filters.range", "limits": "Z[0.1:3.5]"}]}
            pipeline = pdal.Pipeline(json.dumps(pipeline_json))
            pipeline.execute()
            pts_arr = pipeline.arrays[0] if pipeline.arrays else np.array([])
            if len(pts_arr) == 0:
                return {"walls": [], "slabs": [], "openings": [], "rooms": []}
            x, y, z = pts_arr["X"], pts_arr["Y"], pts_arr["Z"]
            x_min, x_max = float(x.min()), float(x.max())
            y_min, y_max = float(y.min()), float(y.max())
            z_min, z_max = float(z.min()), float(z.max())
            return {
                "walls": [
                    {"polygon": [[x_min, y_min], [x_min, y_max]], "height": z_max - z_min, "thickness": 0.2},
                    {"polygon": [[x_max, y_min], [x_max, y_max]], "height": z_max - z_min, "thickness": 0.2},
                    {"polygon": [[x_min, y_min], [x_max, y_min]], "height": z_max - z_min, "thickness": 0.2},
                    {"polygon": [[x_min, y_max], [x_max, y_max]], "height": z_max - z_min, "thickness": 0.2},
                ],
                "slabs": [{"type": "floor", "z": z_min,
                           "polygon": [[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max]],
                           "area_m2": (x_max - x_min) * (y_max - y_min)}],
                "openings": [],
                "rooms": [{"label": "Room",
                           "centroid": [(x_min + x_max) / 2, (y_min + y_max) / 2],
                           "area_m2": (x_max - x_min) * (y_max - y_min)}],
            }
        except Exception:
            return {"walls": [], "slabs": [], "openings": [], "rooms": []}


# ── Geometry helpers ─────────────────────────────────────────────────────────

def _convex_hull_2d(points: np.ndarray) -> list[list[float]]:
    """
    Compute the 2-D convex hull of an (N, 2) array using the gift-wrapping
    algorithm.  Returns a list of [x, y] vertices in counter-clockwise order.
    Falls back to the bounding-box corners if fewer than 3 unique points.
    """
    pts = np.unique(points, axis=0)
    if len(pts) < 3:
        # Degenerate: return bounding box
        x0, y0 = float(pts[:, 0].min()), float(pts[:, 1].min())
        x1, y1 = float(pts[:, 0].max()), float(pts[:, 1].max())
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]

    # Graham scan
    pivot = pts[np.lexsort((pts[:, 1], pts[:, 0]))[0]]

    def _angle(p: np.ndarray) -> float:
        return float(np.arctan2(p[1] - pivot[1], p[0] - pivot[0]))

    sorted_pts = sorted(pts, key=_angle)
    hull = [sorted_pts[0], sorted_pts[1]]
    for p in sorted_pts[2:]:
        while len(hull) > 1:
            o = hull[-2]
            a = hull[-1]
            cross = (a[0] - o[0]) * (p[1] - o[1]) - (a[1] - o[1]) * (p[0] - o[0])
            if cross <= 0:
                hull.pop()
            else:
                break
        hull.append(p)
    return [[float(v[0]), float(v[1])] for v in hull]


def _polygon_area(polygon: list[list[float]]) -> float:
    """Shoelace formula for the signed area of a 2-D polygon."""
    n = len(polygon)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += polygon[i][0] * polygon[j][1]
        area -= polygon[j][0] * polygon[i][1]
    return abs(area) / 2.0


# ── IFC generation ────────────────────────────────────────────────────────────

def generate_ifc(segments: dict, output_ifc: Path, dataset_name: str) -> Path:
    """Generate an IFC 4 file from segmentation results using IfcOpenShell."""
    model = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name=dataset_name)
    ifcopenshell.api.run("unit.assign_si_units", model, length="METRE", area="SQUARE_METRE", volume="CUBIC_METRE")

    context = ifcopenshell.api.run("context.add_context", model, context_type="Model")
    ifcopenshell.api.run(
        "context.add_context", model,
        context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=context,
    )

    site = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSite", name="Site")
    building = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuilding", name=dataset_name)
    storey = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuildingStorey", name="Ground Floor")

    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=project, product=site)
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=site, product=building)
    ifcopenshell.api.run("aggregate.assign_object", model, relating_object=building, product=storey)

    for i, _ in enumerate(segments.get("walls", [])):
        wall = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWall", name=f"Wall-{i+1:03d}")
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, product=wall)

    for i, slab_data in enumerate(segments.get("slabs", [])):
        slab_type = "FLOOR" if slab_data.get("type") == "floor" else "ROOF"
        slab = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSlab",
                                    name=f"Slab-{i+1:03d}", predefined_type=slab_type)
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, product=slab)

    for i, opening in enumerate(segments.get("openings", [])):
        ifc_class = "IfcDoor" if opening.get("type") == "door" else "IfcWindow"
        element = ifcopenshell.api.run("root.create_entity", model, ifc_class=ifc_class,
                                       name=f"{opening.get('type', 'opening').capitalize()}-{i+1:03d}")
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, product=element)

    for i, room in enumerate(segments.get("rooms", [])):
        space = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSpace",
                                     name=room.get("label", f"Room-{i+1:03d}"))
        ifcopenshell.api.run("spatial.assign_container", model, relating_structure=storey, product=space)

    model.write(str(output_ifc))
    log.info("IFC written: %s", output_ifc)
    return output_ifc


# ── DXF floor plan generation ─────────────────────────────────────────────────

def generate_dxf_floor_plan(segments: dict, output_dxf: Path) -> Path:
    """Generate a DXF floor plan from segmentation results using ezdxf."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()

    doc.layers.add("WALLS", color=7)
    doc.layers.add("DOORS", color=3)
    doc.layers.add("WINDOWS", color=5)
    doc.layers.add("ROOMS", color=2)
    doc.layers.add("DIMENSIONS", color=1)

    for wall in segments.get("walls", []):
        pts = wall.get("polygon", [])
        for j in range(len(pts) - 1):
            msp.add_line(
                (pts[j][0], pts[j][1]),
                (pts[j+1][0], pts[j+1][1]),
                dxfattribs={"layer": "WALLS", "lineweight": 50},
            )

    for opening in segments.get("openings", []):
        if opening.get("type") == "door":
            cx, cy = opening.get("center", [0, 0])[:2]
            width = opening.get("width", 0.9)
            msp.add_arc(
                center=(cx, cy), radius=width,
                start_angle=0, end_angle=90,
                dxfattribs={"layer": "DOORS"},
            )
            msp.add_line((cx, cy), (cx + width, cy), dxfattribs={"layer": "DOORS"})
        elif opening.get("type") == "window":
            pts = opening.get("polygon", [])
            if len(pts) >= 2:
                msp.add_line(
                    (pts[0][0], pts[0][1]),
                    (pts[-1][0], pts[-1][1]),
                    dxfattribs={"layer": "WINDOWS", "lineweight": 25},
                )

    for room in segments.get("rooms", []):
        cx, cy = room.get("centroid", [0, 0])[:2]
        label = room.get("label", "Room")
        area = room.get("area_m2", 0)
        msp.add_text(
            f"{label} {area:.1f}m2",
            dxfattribs={"layer": "ROOMS", "height": 0.2, "insert": (cx, cy)},
        )

    doc.saveas(str(output_dxf))
    log.info("DXF written: %s", output_dxf)
    return output_dxf


# ── Main processing loop ──────────────────────────────────────────────────────

def process_job(job: dict) -> None:
    job_id = job["id"]
    dataset = job.get("datasets") or {}
    dataset_id = dataset.get("id") or job.get("dataset_id")
    org_id = dataset.get("organization_id") or job.get("organization_id")
    raw_key = dataset.get("s3_raw_key") or job.get("parameters", {}).get("r2_input_key")

    if not raw_key:
        raise ValueError("Job has no s3_raw_key / r2_input_key")

    log.info("Processing job %s | dataset %s | key %s", job_id, dataset_id, raw_key)

    with tempfile.TemporaryDirectory(prefix="bim_") as tmpdir:
        tmp = Path(tmpdir)
        input_ext = Path(raw_key).suffix or ".laz"
        input_laz = tmp / f"input{input_ext}"
        preprocessed_laz = tmp / "preprocessed.laz"
        segments_dir = tmp / "segments"
        output_ifc = tmp / f"{dataset_id}.ifc"
        output_dxf = tmp / f"{dataset_id}.dxf"
        segments_json_path = tmp / "segments.json"

        # Step 1: Download
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 10)
        download_from_r2(raw_key, input_laz)

        # Step 2: Pre-process
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 25)
        preprocess_point_cloud(input_laz, preprocessed_laz)

        # Step 3: Cloud2BIM segmentation
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 45)
        segments = run_cloud2bim_segmentation(preprocessed_laz, segments_dir)

        # Step 4: Generate IFC
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 65)
        dataset_record = supabase.table("datasets").select("name").eq("id", dataset_id).single().execute()
        dataset_name = dataset_record.data.get("name", dataset_id) if dataset_record.data else dataset_id
        generate_ifc(segments, output_ifc, dataset_name)

        # Step 5: Generate DXF
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 80)
        generate_dxf_floor_plan(segments, output_dxf)

        # Step 6: Upload outputs to R2
        update_job(job_id, "processing", 90)
        base_key = f"processed/{org_id}/{dataset_id}"
        ifc_key = f"{base_key}/{dataset_id}.ifc"
        dxf_key = f"{base_key}/{dataset_id}.dxf"
        segments_key = f"{base_key}/segments.json"

        ifc_url = upload_to_r2(output_ifc, ifc_key, "application/x-step")
        dxf_url = upload_to_r2(output_dxf, dxf_key, "application/dxf")
        segments_json_path.write_text(json.dumps(segments))
        upload_to_r2(segments_json_path, segments_key, "application/json")

        # Step 7: Update Supabase
        supabase.table("datasets").update({
            "ifc_url": ifc_url,
            "dxf_url": dxf_url,
            "segments_url": f"{R2_PUBLIC_BASE}/{segments_key}",
            "bim_stats": {
                "wall_count": len(segments["walls"]),
                "slab_count": len(segments["slabs"]),
                "opening_count": len(segments["openings"]),
                "room_count": len(segments["rooms"]),
            },
        }).eq("id", dataset_id).execute()

        update_job(job_id, "completed", 100, result_url=ifc_url)
        log.info("BIM extraction complete: job=%s", job_id)


def main() -> None:
    log.info("BIM Extraction Worker started — polling Supabase | interval=%ds", POLL_INTERVAL)
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
            time.sleep(min(POLL_INTERVAL * consecutive_errors, 120))


if __name__ == "__main__":
    main()
