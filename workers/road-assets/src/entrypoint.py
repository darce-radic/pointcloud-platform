"""
Road Assets Worker — Automated extraction of road infrastructure from LiDAR point clouds.

Extracts and classifies:
  - Road markings (lines, arrows, crosswalks) via intensity-based segmentation
  - Traffic signs (detection + type classification via PointPillars/OpenPCDet)
  - Road drains and manholes (DTM local minima analysis)

Pipeline:
  1. Poll Supabase `processing_jobs` for status='queued' and job_type='road_asset_extraction'
  2. Claim the job atomically (status → 'processing')
  3. Download LAZ/COPC from Cloudflare R2
  4. PDAL pre-processing (ground classification, DTM generation)
  5. Road surface extraction (intensity + planarity filtering)
  6. Road marking vectorization
  7. Traffic sign detection (OpenPCDet PointPillars model or geometric fallback)
  8. Drain/manhole detection (DTM local minima)
  9. Export to GeoJSON, upload to R2, update Supabase

Environment variables required:
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
  R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME
  R2_PUBLIC_BASE_URL
  POLL_INTERVAL_SECONDS  (default: 10)
  OPENPCDET_MODEL_PATH   (optional, defaults to /models/pointpillars_traffic_signs.pth)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, List, Dict

import boto3
from botocore.config import Config
import numpy as np
import pdal
from scipy import ndimage
from scipy.spatial import cKDTree
from shapely.geometry import mapping
from shapely.ops import unary_union
from supabase import create_client, Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("road-assets-worker")

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
MODEL_PATH = os.environ.get("OPENPCDET_MODEL_PATH", "/models/pointpillars_traffic_signs.pth")

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
    Atomically claim one queued road_asset_extraction job.
    Falls back to a simple poll for single-worker deployments.
    """
    # Fallback: simple poll (safe for single-worker deployments)
    result = (
        supabase.table("processing_jobs")
        .select("*, datasets(id, name, s3_raw_key, organization_id)")
        .eq("status", "queued")
        .eq("job_type", "road_asset_extraction")
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


def upload_to_r2(local_path: Path, r2_key: str) -> str:
    log.info("Uploading %s → r2://%s/%s", local_path, R2_BUCKET, r2_key)
    r2.upload_file(
        str(local_path),
        R2_BUCKET,
        r2_key,
        ExtraArgs={"ContentType": "application/geo+json"},
    )
    return f"{R2_PUBLIC_BASE}/{r2_key}"


# ── Step 1: PDAL pre-processing ───────────────────────────────────────────────

def preprocess_and_classify(input_laz: Path, output_laz: Path, dtm_tif: Path) -> np.ndarray:
    """
    Ground classification + DTM generation + road surface extraction.
    Returns the full point array for downstream processing.
    """
    pipeline_json = {
        "pipeline": [
            str(input_laz),
            {"type": "filters.outlier", "method": "statistical", "mean_k": 12, "multiplier": 2.5},
            {"type": "filters.smrf", "window": 18.0, "slope": 0.15, "threshold": 0.5, "cell": 1.0},
            {"type": "filters.hag_nn", "count": 5},
            {"type": "writers.las", "filename": str(output_laz), "compression": "laszip"},
            {
                "type": "writers.gdal",
                "filename": str(dtm_tif),
                "dimension": "Z",
                "resolution": 0.1,
                "radius": 0.5,
                "output_type": "min",
                "gdaldriver": "GTiff",
                "where": "Classification == 2",
            },
        ]
    }
    pipeline = pdal.Pipeline(json.dumps(pipeline_json))
    pipeline.execute()
    arrays = pipeline.arrays
    return arrays[0] if arrays else np.array([])


# ── Step 2: Road surface extraction ──────────────────────────────────────────

def extract_road_surface(points: np.ndarray) -> np.ndarray:
    if len(points) == 0:
        return np.array([])
    hag = points["HeightAboveGround"] if "HeightAboveGround" in points.dtype.names else np.zeros(len(points))
    intensity = points["Intensity"] if "Intensity" in points.dtype.names else np.ones(len(points)) * 100
    road_mask = (hag < 0.15) & (intensity > 20) & (intensity < 220)
    log.info("Road surface: %d of %d points", road_mask.sum(), len(points))
    return points[road_mask]


# ── Step 3: Road marking extraction ──────────────────────────────────────────

def extract_road_markings(road_points: np.ndarray) -> List[Dict]:
    if len(road_points) == 0:
        return []

    intensity = road_points["Intensity"] if "Intensity" in road_points.dtype.names else np.ones(len(road_points))
    x = road_points["X"]
    y = road_points["Y"]

    median_intensity = np.median(intensity)
    marking_threshold = median_intensity * 1.8
    marking_mask = intensity > marking_threshold

    if marking_mask.sum() < 10:
        return []

    marking_pts = np.column_stack([x[marking_mask], y[marking_mask]])
    tree = cKDTree(marking_pts)
    visited = np.zeros(len(marking_pts), dtype=bool)
    clusters = []

    for i in range(len(marking_pts)):
        if visited[i]:
            continue
        neighbors = tree.query_ball_point(marking_pts[i], r=0.3)
        if len(neighbors) >= 5:
            visited[neighbors] = True
            clusters.append(neighbors)

    features = []
    for cluster_indices in clusters:
        cluster_pts = marking_pts[cluster_indices]
        if len(cluster_pts) < 3:
            continue
        x_range = cluster_pts[:, 0].max() - cluster_pts[:, 0].min()
        y_range = cluster_pts[:, 1].max() - cluster_pts[:, 1].min()
        aspect = max(x_range, y_range) / (min(x_range, y_range) + 0.001)
        marking_type = "lane_line" if aspect > 5 else ("arrow" if aspect > 2 else "symbol")
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

    log.info("Road markings detected: %d", len(features))
    return features


# ── Step 4: Traffic sign detection ───────────────────────────────────────────

def detect_traffic_signs(input_laz: Path) -> List[Dict]:
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
                        "geometry": {"type": "Point", "coordinates": [det["x"], det["y"], det["z"]]},
                        "properties": {
                            "asset_type": "traffic_sign",
                            "sign_class": det.get("class", "unknown"),
                            "confidence": det.get("score", 0.0),
                            "height_m": det.get("z", 0.0),
                        },
                    })
                log.info("Traffic signs detected (OpenPCDet): %d", len(features))
                return features
        except Exception as e:
            log.warning("OpenPCDet inference failed, using geometric fallback: %s", e)

    # Geometric fallback
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
                    features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [
                            float(np.mean(x[neighbors])),
                            float(np.mean(y[neighbors])),
                            float(np.mean(z[neighbors])),
                        ]},
                        "properties": {
                            "asset_type": "traffic_sign",
                            "sign_class": "unknown",
                            "confidence": 0.5,
                            "detection_method": "geometric_fallback",
                        },
                    })
    except Exception as e:
        log.warning("Geometric sign detection failed: %s", e)

    log.info("Traffic signs detected (geometric): %d", len(features))
    return features


# ── Step 5: Street light pole detection ─────────────────────────────────────

def detect_street_light_poles(points: np.ndarray) -> List[Dict]:
    """
    Detect street light poles using PDAL height-above-ground + vertical cluster analysis.

    Algorithm:
      1. Keep points with HeightAboveGround in [3.0, 12.0] m (pole height band).
      2. Cluster in XY using a 0.5 m radius cKDTree search.
      3. Accept clusters with 10–500 points whose XY spread is < 0.6 m
         (thin vertical objects) and Z spread is > 2.0 m (tall).
      4. Classify as 'street_light' (Z centroid > 6 m) or 'sign_pole' otherwise.
    """
    features: List[Dict] = []
    try:
        if len(points) == 0:
            return features
        hag_field = "HeightAboveGround" if "HeightAboveGround" in points.dtype.names else None
        if hag_field is None:
            return features

        hag = points[hag_field]
        pole_mask = (hag >= 3.0) & (hag <= 12.0)
        if pole_mask.sum() < 10:
            return features

        pole_pts = points[pole_mask]
        x = pole_pts["X"]
        y = pole_pts["Y"]
        z = pole_pts["Z"]

        xy = np.column_stack([x, y])
        tree = cKDTree(xy)
        visited = np.zeros(len(pole_pts), dtype=bool)

        for i in range(len(pole_pts)):
            if visited[i]:
                continue
            neighbors = tree.query_ball_point(xy[i], r=0.5)
            if not (10 <= len(neighbors) <= 500):
                continue
            n_idx = np.array(neighbors)
            cx_pts = x[n_idx]
            cy_pts = y[n_idx]
            cz_pts = z[n_idx]
            xy_spread = max(
                float(cx_pts.max() - cx_pts.min()),
                float(cy_pts.max() - cy_pts.min()),
            )
            z_spread = float(cz_pts.max() - cz_pts.min())
            if xy_spread > 0.6 or z_spread < 2.0:
                continue
            visited[n_idx] = True
            cx = float(np.mean(cx_pts))
            cy_val = float(np.mean(cy_pts))
            cz = float(np.mean(cz_pts))
            asset_type = "street_light" if cz > 6.0 else "sign_pole"
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [cx, cy_val, cz]},
                "properties": {
                    "asset_type": asset_type,
                    "height_m": round(z_spread, 2),
                    "xy_spread_m": round(xy_spread, 3),
                    "point_count": len(neighbors),
                    "detection_method": "geometric_hag",
                },
            })
    except Exception as e:
        log.warning("Street light pole detection failed: %s", e)
    log.info("Street light poles detected: %d", len(features))
    return features


# ── Step 6: Kerb geometry detection ──────────────────────────────────────────

def detect_kerb_geometry(points: np.ndarray) -> List[Dict]:
    """
    Detect kerb and gutter geometry using height discontinuity analysis.

    Algorithm:
      1. Keep points with HeightAboveGround in [0.05, 0.35] m — the kerb height band.
      2. Cluster in XY using a 0.4 m radius search.
      3. Accept elongated clusters (aspect ratio > 4) with ≥ 20 points.
      4. Fit a line segment to each cluster and emit it as a LineString feature.
    """
    features: List[Dict] = []
    try:
        if len(points) == 0:
            return features
        hag_field = "HeightAboveGround" if "HeightAboveGround" in points.dtype.names else None
        if hag_field is None:
            return features

        hag = points[hag_field]
        kerb_mask = (hag >= 0.05) & (hag <= 0.35)
        if kerb_mask.sum() < 20:
            return features

        kerb_pts = points[kerb_mask]
        x = kerb_pts["X"]
        y = kerb_pts["Y"]

        xy = np.column_stack([x, y])
        tree = cKDTree(xy)
        visited = np.zeros(len(kerb_pts), dtype=bool)

        for i in range(len(kerb_pts)):
            if visited[i]:
                continue
            neighbors = tree.query_ball_point(xy[i], r=0.4)
            if len(neighbors) < 20:
                continue
            n_idx = np.array(neighbors)
            cx_pts = x[n_idx]
            cy_pts = y[n_idx]
            x_range = float(cx_pts.max() - cx_pts.min())
            y_range = float(cy_pts.max() - cy_pts.min())
            long_axis = max(x_range, y_range)
            short_axis = min(x_range, y_range) + 0.001
            if long_axis / short_axis < 4.0:
                continue
            visited[n_idx] = True

            # PCA to find the principal axis direction
            cluster_xy = np.column_stack([cx_pts, cy_pts])
            centroid = cluster_xy.mean(axis=0)
            _, _, Vt = np.linalg.svd(cluster_xy - centroid)
            direction = Vt[0]  # Principal axis
            proj = (cluster_xy - centroid) @ direction
            start = centroid + float(proj.min()) * direction
            end = centroid + float(proj.max()) * direction
            length = float(np.linalg.norm(end - start))

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [float(start[0]), float(start[1])],
                        [float(end[0]),   float(end[1])],
                    ],
                },
                "properties": {
                    "asset_type": "kerb",
                    "length_m": round(length, 2),
                    "point_count": len(neighbors),
                    "detection_method": "geometric_hag",
                },
            })
    except Exception as e:
        log.warning("Kerb geometry detection failed: %s", e)
    log.info("Kerb segments detected: %d", len(features))
    return features


# ── Step 7: Drain and manhole detection ──────────────────────────────────────

def detect_drains(dtm_tif: Path, road_points: np.ndarray) -> List[Dict]:
    features = []
    try:
        import rasterio
        with rasterio.open(str(dtm_tif)) as src:
            dtm = src.read(1)
            transform = src.transform
            eroded = ndimage.grey_erosion(dtm, size=(5, 5))
            local_min_mask = (dtm < eroded + 0.02) & (dtm != src.nodata)
            labeled, num_features = ndimage.label(local_min_mask)
            for label_id in range(1, num_features + 1):
                component = labeled == label_id
                area_m2 = component.sum() * (src.res[0] * src.res[1])
                if not (0.05 <= area_m2 <= 4.0):
                    continue
                rows, cols = np.where(component)
                cx, cy = rasterio.transform.xy(transform, int(np.mean(rows)), int(np.mean(cols)))
                depth = float(np.min(dtm[component]) - np.mean(dtm[~component & (labeled == 0)]))
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [cx, cy]},
                    "properties": {
                        "asset_type": "manhole" if area_m2 > 0.5 else "drain",
                        "area_m2": round(area_m2, 3),
                        "depth_m": round(abs(depth), 3),
                    },
                })
    except ImportError:
        log.warning("rasterio not available — skipping drain detection")
    except Exception as e:
        log.warning("Drain detection failed: %s", e)
    log.info("Drains/manholes detected: %d", len(features))
    return features


# ── Step 8: Assemble GeoJSON output ────────────────────────────────────────────────

def build_geojson(
    road_markings: List[Dict],
    traffic_signs: List[Dict],
    drains: List[Dict],
    street_lights: List[Dict],
    kerbs: List[Dict],
) -> dict:
    all_features = road_markings + traffic_signs + drains + street_lights + kerbs
    return {
        "type": "FeatureCollection",
        "features": all_features,
        "metadata": {
            "road_marking_count": len(road_markings),
            "traffic_sign_count": len(traffic_signs),
            "drain_count": len(drains),
            "street_light_count": len(street_lights),
            "kerb_segment_count": len(kerbs),
            "total_features": len(all_features),
        },
    }


# ── Main processing loop ────────────────────────────────────────────────

def process_job(job: dict) -> None:
    job_id = job["id"]
    dataset = job.get("datasets") or {}
    dataset_id = dataset.get("id") or job.get("dataset_id")
    org_id = dataset.get("organization_id") or job.get("organization_id")
    raw_key = dataset.get("s3_raw_key") or job.get("parameters", {}).get("r2_input_key")

    if not raw_key:
        raise ValueError("Job has no s3_raw_key / r2_input_key")

    log.info("Processing job %s | dataset %s | key %s", job_id, dataset_id, raw_key)

    with tempfile.TemporaryDirectory(prefix="road_assets_") as tmpdir:
        tmp = Path(tmpdir)
        input_ext = Path(raw_key).suffix or ".laz"
        input_laz = tmp / f"input{input_ext}"
        classified_laz = tmp / "classified.laz"
        dtm_tif = tmp / "dtm.tif"
        output_geojson = tmp / f"{dataset_id}_road_assets.geojson"

        # Step 1: Download
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 10)
        download_from_r2(raw_key, input_laz)

        # Step 2: Pre-process and classify
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 20)
        all_points = preprocess_and_classify(input_laz, classified_laz, dtm_tif)

        # Step 3: Extract road surface
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 35)
        road_points = extract_road_surface(all_points)

        # Step 4: Road markings
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 50)
        road_markings = extract_road_markings(road_points)

        # Step 5: Traffic signs
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 65)
        traffic_signs = detect_traffic_signs(classified_laz)

        # Step 6: Street light poles
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 72)
        street_lights = detect_street_light_poles(all_points)

        # Step 7: Kerb geometry
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 78)
        kerbs = detect_kerb_geometry(all_points)

        # Step 8: Drains
        if is_cancelled(job_id):
            update_job(job_id, "cancelled")
            return
        update_job(job_id, "processing", 84)
        drains = detect_drains(dtm_tif, road_points)

        # Step 9: Build and upload GeoJSON
        update_job(job_id, "processing", 92)
        geojson = build_geojson(road_markings, traffic_signs, drains, street_lights, kerbs)
        output_geojson.write_text(json.dumps(geojson, indent=2))

        geojson_key = f"processed/{org_id}/{dataset_id}/{dataset_id}_road_assets.geojson"
        public_url = upload_to_r2(output_geojson, geojson_key)

        # Step 8: Update Supabase
        supabase.table("datasets").update({
            "road_assets_url": public_url,
            "road_asset_stats": geojson["metadata"],
        }).eq("id", dataset_id).execute()

        update_job(job_id, "completed", 100, result_url=public_url)
        log.info(
            "Road asset extraction complete: job=%s, features=%d",
            job_id,
            geojson["metadata"]["total_features"],
        )


def main() -> None:
    log.info("Road Assets Worker started — polling Supabase | interval=%ds", POLL_INTERVAL)
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
