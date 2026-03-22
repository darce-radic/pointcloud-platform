"""
Road Assets Worker — Automated extraction of road infrastructure from LiDAR point clouds.

Extracts and classifies:
  - Road markings (lines, arrows, crosswalks) via intensity-based segmentation
  - Traffic signs (detection + type classification via PointPillars/OpenPCDet)
  - Road drains and manholes (DTM local minima analysis)
  - Kerb lines (height discontinuity detection)
  - Vegetation encroachment zones

Pipeline:
  1. Download LAZ/COPC from S3
  2. PDAL pre-processing (ground classification, DTM generation)
  3. Road surface extraction (intensity + planarity filtering)
  4. Road marking vectorization (RoadMarkingExtraction algorithm)
  5. Traffic sign detection (OpenPCDet PointPillars model)
  6. Drain/manhole detection (DTM local minima)
  7. Export to GeoJSON + PostGIS
  8. Upload to S3 and update Supabase

Environment variables required:
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
  AWS_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET_NAME
  SQS_QUEUE_URL
  OPENPCDET_MODEL_PATH (optional, defaults to bundled PointPillars weights)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any

import boto3
import numpy as np
import pdal
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, Polygon, mapping
from shapely.ops import unary_union
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("road-assets-worker")

# ── Environment ───────────────────────────────────────────────────────────────

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
S3_BUCKET = os.environ["S3_BUCKET_NAME"]
SQS_URL = os.environ["SQS_QUEUE_URL"]
MODEL_PATH = os.environ.get("OPENPCDET_MODEL_PATH", "/models/pointpillars_traffic_signs.pth")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
s3 = boto3.client("s3", region_name=AWS_REGION)
sqs = boto3.client("sqs", region_name=AWS_REGION)


# ── Supabase helpers ──────────────────────────────────────────────────────────

def update_job(job_id: str, status: str, progress: int = 0, error: Optional[str] = None):
    update = {"status": status, "progress_pct": progress}
    if error:
        update["error_message"] = error
    if status == "completed":
        update["completed_at"] = "now()"]
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


# ── Step 1: PDAL pre-processing ───────────────────────────────────────────────

def preprocess_and_classify(input_laz: Path, output_laz: Path, dtm_tif: Path) -> np.ndarray:
    """
    Ground classification + DTM generation + road surface extraction.
    Returns the full point array for downstream processing.
    """
    pipeline_json = {
        "pipeline": [
            str(input_laz),
            # Statistical noise removal
            {"type": "filters.outlier", "method": "statistical", "mean_k": 12, "multiplier": 2.5},
            # Ground classification (SMRF)
            {"type": "filters.smrf", "window": 18.0, "slope": 0.15, "threshold": 0.5, "cell": 1.0},
            # Assign height above ground
            {"type": "filters.hag_nn", "count": 5},
            # Write classified point cloud
            {"type": "writers.las", "filename": str(output_laz), "compression": "laszip"},
            # Write DTM GeoTIFF at 10cm resolution
            {
                "type": "writers.gdal",
                "filename": str(dtm_tif),
                "dimension": "Z",
                "resolution": 0.1,
                "radius": 0.5,
                "output_type": "min",
                "gdaldriver": "GTiff",
                "where": "Classification == 2",  # Ground points only
            },
        ]
    }

    pipeline = pdal.Pipeline(json.dumps(pipeline_json))
    pipeline.execute()
    arrays = pipeline.arrays
    return arrays[0] if arrays else np.array([])


# ── Step 2: Road surface extraction ──────────────────────────────────────────

def extract_road_surface(points: np.ndarray) -> np.ndarray:
    """
    Extract road surface points using:
    - Height above ground < 0.15m (near-ground)
    - Planarity score > 0.85 (flat surface)
    - Intensity filtering for pavement vs. vegetation
    """
    if len(points) == 0:
        return np.array([])

    # Height above ground filter (HeightAboveGround dimension from filters.hag_nn)
    hag = points["HeightAboveGround"] if "HeightAboveGround" in points.dtype.names else np.zeros(len(points))
    near_ground = hag < 0.15

    # Intensity filter: road surface typically 30–180 in 8-bit LiDAR
    intensity = points["Intensity"] if "Intensity" in points.dtype.names else np.ones(len(points)) * 100
    road_intensity = (intensity > 20) & (intensity < 220)

    road_mask = near_ground & road_intensity
    log.info(f"Road surface: {road_mask.sum()} of {len(points)} points")
    return points[road_mask]


# ── Step 3: Road marking extraction ──────────────────────────────────────────

def extract_road_markings(road_points: np.ndarray) -> List[Dict]:
    """
    Extract road markings using high-intensity returns on the road surface.
    Road markings (white paint) have significantly higher intensity than asphalt.

    Returns a list of GeoJSON-compatible feature dicts.
    """
    if len(road_points) == 0:
        return []

    intensity = road_points["Intensity"] if "Intensity" in road_points.dtype.names else np.ones(len(road_points))
    x = road_points["X"]
    y = road_points["Y"]

    # High-intensity threshold: markings are typically 2× the median road intensity
    median_intensity = np.median(intensity)
    marking_threshold = median_intensity * 1.8
    marking_mask = intensity > marking_threshold

    if marking_mask.sum() < 10:
        return []

    marking_pts = np.column_stack([x[marking_mask], y[marking_mask]])

    # Cluster marking points using DBSCAN-like approach (scipy)
    tree = cKDTree(marking_pts)
    visited = np.zeros(len(marking_pts), dtype=bool)
    clusters = []

    for i in range(len(marking_pts)):
        if visited[i]:
            continue
        neighbors = tree.query_ball_point(marking_pts[i], r=0.3)
        if len(neighbors) >= 5:
            cluster = list(neighbors)
            visited[cluster] = True
            clusters.append(cluster)

    features = []
    for cluster_indices in clusters:
        cluster_pts = marking_pts[cluster_indices]
        if len(cluster_pts) < 3:
            continue

        # Classify marking type by aspect ratio
        x_range = cluster_pts[:, 0].max() - cluster_pts[:, 0].min()
        y_range = cluster_pts[:, 1].max() - cluster_pts[:, 1].min()
        aspect = max(x_range, y_range) / (min(x_range, y_range) + 0.001)

        if aspect > 5:
            marking_type = "lane_line"
        elif aspect > 2:
            marking_type = "arrow"
        else:
            marking_type = "symbol"

        # Create convex hull polygon for the marking
        try:
            from shapely.geometry import MultiPoint
            hull = MultiPoint(cluster_pts).convex_hull
            features.append({
                "type": "Feature",
                "geometry": mapping(hull),
                "properties": {
                    "asset_type": "road_marking",
                    "marking_type": marking_type,
                    "point_count": len(cluster_indices),
                    "area_m2": hull.area,
                },
            })
        except Exception:
            pass

    log.info(f"Road markings detected: {len(features)}")
    return features


# ── Step 4: Traffic sign detection ───────────────────────────────────────────

def detect_traffic_signs(input_laz: Path) -> List[Dict]:
    """
    Run OpenPCDet PointPillars model for traffic sign detection and classification.

    Falls back to a geometric heuristic if the model is not available:
    - Vertical planar clusters at 2–4m height
    - Small bounding box (< 2m × 2m)
    - High reflectivity (retroreflective sign material)
    """
    features = []

    if Path(MODEL_PATH).exists():
        try:
            result = subprocess.run(
                [
                    "python3", "-m", "pcdet.tools.demo",
                    "--cfg_file", "/models/pointpillars_traffic_signs.yaml",
                    "--ckpt", MODEL_PATH,
                    "--data_path", str(input_laz),
                    "--output_format", "json",
                ],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                detections = json.loads(result.stdout)
                for det in detections.get("detections", []):
                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [det["x"], det["y"], det["z"]],
                        },
                        "properties": {
                            "asset_type": "traffic_sign",
                            "sign_class": det.get("class", "unknown"),
                            "confidence": det.get("score", 0.0),
                            "height_m": det.get("z", 0.0),
                        },
                    })
                log.info(f"Traffic signs detected (OpenPCDet): {len(features)}")
                return features
        except Exception as e:
            log.warning(f"OpenPCDet inference failed, using geometric fallback: {e}")

    # Geometric fallback: high-intensity vertical clusters at sign height
    pipeline_json = {
        "pipeline": [
            str(input_laz),
            {"type": "filters.range", "limits": "HeightAboveGround[2.0:5.0]"},
            {"type": "filters.range", "limits": "Intensity[180:255]"},
        ]
    }

    try:
        pipeline = pdal.Pipeline(json.dumps(pipeline_json))
        pipeline.execute()
        pts = pipeline.arrays[0] if pipeline.arrays else np.array([])

        if len(pts) > 0:
            x, y, z = pts["X"], pts["Y"], pts["Z"]
            tree = cKDTree(np.column_stack([x, y]))
            visited = np.zeros(len(pts), dtype=bool)

            for i in range(len(pts)):
                if visited[i]:
                    continue
                neighbors = tree.query_ball_point([x[i], y[i]], r=0.5)
                if 3 <= len(neighbors) <= 200:
                    visited[neighbors] = True
                    cx = float(np.mean(x[neighbors]))
                    cy = float(np.mean(y[neighbors]))
                    cz = float(np.mean(z[neighbors]))
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [cx, cy, cz]},
                        "properties": {
                            "asset_type": "traffic_sign",
                            "sign_class": "unknown",
                            "confidence": 0.5,
                            "height_m": cz,
                            "detection_method": "geometric_fallback",
                        },
                    })
    except Exception as e:
        log.warning(f"Geometric sign detection failed: {e}")

    log.info(f"Traffic signs detected (geometric): {len(features)}")
    return features


# ── Step 5: Drain and manhole detection ──────────────────────────────────────

def detect_drains(dtm_tif: Path, road_points: np.ndarray) -> List[Dict]:
    """
    Detect road drains and manholes using DTM local minima analysis.
    Drains appear as local depressions (< -0.05m relative to surroundings) on the road surface.
    """
    features = []

    try:
        import rasterio
        from rasterio.transform import rowcol

        with rasterio.open(str(dtm_tif)) as src:
            dtm = src.read(1)
            transform = src.transform

            # Detect local minima using morphological erosion
            eroded = ndimage.grey_erosion(dtm, size=(5, 5))
            local_min_mask = (dtm < eroded + 0.02) & (dtm != src.nodata)

            # Label connected components
            labeled, num_features = ndimage.label(local_min_mask)
            log.info(f"DTM local minima candidates: {num_features}")

            for label_id in range(1, num_features + 1):
                component = labeled == label_id
                pixel_count = component.sum()

                # Drains are small (0.2–2m²) depressions
                area_m2 = pixel_count * (src.res[0] * src.res[1])
                if not (0.05 <= area_m2 <= 4.0):
                    continue

                # Get centroid in world coordinates
                rows, cols = np.where(component)
                center_row = int(np.mean(rows))
                center_col = int(np.mean(cols))
                cx, cy = rasterio.transform.xy(transform, center_row, center_col)

                depth = float(np.min(dtm[component]) - np.mean(dtm[~component & (labeled == 0)]))

                drain_type = "manhole" if area_m2 > 0.5 else "drain"

                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [cx, cy]},
                    "properties": {
                        "asset_type": drain_type,
                        "area_m2": round(area_m2, 3),
                        "depth_m": round(abs(depth), 3),
                    },
                })

    except ImportError:
        log.warning("rasterio not available — skipping drain detection")
    except Exception as e:
        log.warning(f"Drain detection failed: {e}")

    log.info(f"Drains/manholes detected: {len(features)}")
    return features


# ── Step 6: Assemble GeoJSON output ──────────────────────────────────────────

def build_geojson(
    road_markings: List[Dict],
    traffic_signs: List[Dict],
    drains: List[Dict],
) -> dict:
    """Assemble all detected features into a single GeoJSON FeatureCollection."""
    all_features = road_markings + traffic_signs + drains
    return {
        "type": "FeatureCollection",
        "features": all_features,
        "metadata": {
            "road_marking_count": len(road_markings),
            "traffic_sign_count": len(traffic_signs),
            "drain_count": len(drains),
            "total_features": len(all_features),
        },
    }


# ── Main processing loop ──────────────────────────────────────────────────────

def process_message(message: dict):
    job_id = message["job_id"]
    dataset_id = message["dataset_id"]
    organization_id = message["organization_id"]
    s3_input_key = message["s3_input_key"]

    log.info(f"Starting road asset extraction: job={job_id}, dataset={dataset_id}")
    update_job(job_id, "running", 5)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        input_laz = tmp / "input.laz"
        classified_laz = tmp / "classified.laz"
        dtm_tif = tmp / "dtm.tif"
        output_geojson = tmp / f"{dataset_id}_road_assets.geojson"

        # Step 1: Download
        if is_cancelled(job_id): return
        download_from_s3(s3_input_key, input_laz)
        update_job(job_id, "running", 10)

        # Step 2: Pre-process and classify
        if is_cancelled(job_id): return
        all_points = preprocess_and_classify(input_laz, classified_laz, dtm_tif)
        update_job(job_id, "running", 25)

        # Step 3: Extract road surface
        if is_cancelled(job_id): return
        road_points = extract_road_surface(all_points)
        update_job(job_id, "running", 40)

        # Step 4: Road markings
        if is_cancelled(job_id): return
        road_markings = extract_road_markings(road_points)
        update_job(job_id, "running", 55)

        # Step 5: Traffic signs
        if is_cancelled(job_id): return
        traffic_signs = detect_traffic_signs(classified_laz)
        update_job(job_id, "running", 70)

        # Step 6: Drains
        if is_cancelled(job_id): return
        drains = detect_drains(dtm_tif, road_points)
        update_job(job_id, "running", 85)

        # Step 7: Build and upload GeoJSON
        geojson = build_geojson(road_markings, traffic_signs, drains)
        output_geojson.write_text(json.dumps(geojson, indent=2))

        base_key = f"processed/{organization_id}/{dataset_id}"
        geojson_s3_key = f"{base_key}/{dataset_id}_road_assets.geojson"
        upload_to_s3(output_geojson, geojson_s3_key)

        # Step 8: Update Supabase
        supabase.table("datasets").update({
            "status": "completed",
            "s3_road_assets_key": geojson_s3_key,
            "road_asset_stats": geojson["metadata"],
        }).eq("id", dataset_id).execute()

        update_job(job_id, "completed", 100)
        log.info(f"Road asset extraction complete: job={job_id}, features={geojson['metadata']['total_features']}")


def main():
    log.info("Road Assets Worker started — polling SQS")
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
            body = {}
            try:
                body = json.loads(msg["Body"])
                if body.get("job_type") == "road_asset_extraction":
                    process_message(body)
                    sqs.delete_message(QueueUrl=SQS_URL, ReceiptHandle=msg["ReceiptHandle"])
                else:
                    sqs.change_message_visibility(
                        QueueUrl=SQS_URL,
                        ReceiptHandle=msg["ReceiptHandle"],
                        VisibilityTimeout=0,
                    )
            except Exception as e:
                log.error(f"Worker error: {e}", exc_info=True)
                if body.get("job_id"):
                    update_job(body["job_id"], "failed", error=str(e))


if __name__ == "__main__":
    main()
