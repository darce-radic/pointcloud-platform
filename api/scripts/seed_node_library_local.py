"""
Node Library Seed Script — Local Embedding Variant
===================================================
Uses sentence-transformers (all-MiniLM-L6-v2 → projected to 1536 dims)
to generate embeddings without requiring a real OpenAI API key.

This is the recommended approach for CI/CD pipelines and local development.
In production, you can swap to the OpenAI-based seed_node_library.py once
you have a valid OpenAI API key.

Usage:
    python api/scripts/seed_node_library_local.py

Requirements:
    - SUPABASE_URL and SUPABASE_SERVICE_KEY env vars set
    - pip install supabase sentence-transformers

The script is idempotent: it upserts on node_type so it is safe to re-run.
"""
from __future__ import annotations

import os
import sys
import json

try:
    from supabase import create_client, Client
    from sentence_transformers import SentenceTransformer
    import numpy as np
except ImportError:
    print("ERROR: Missing dependencies. Run: pip install supabase sentence-transformers")
    sys.exit(1)

# ── Configuration ─────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", os.environ.get("SUPABASE_ANON_KEY", ""))
# all-MiniLM-L6-v2 produces 384-dim vectors; we project to 1536 to match the
# pgvector column dimension (which was set for text-embedding-3-small).
LOCAL_MODEL = "all-MiniLM-L6-v2"
TARGET_DIM = 1536

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    sys.exit(1)

# ── Node library (identical to seed_node_library.py) ─────────────────────────
NODE_LIBRARY = [
    {
        "node_type": "pdal.read_s3",
        "display_name": "Read Point Cloud from R2/S3",
        "category": "io",
        "description": (
            "Read a raw point cloud file (LAS, LAZ, E57, or PLY) from Cloudflare R2 or any S3-compatible "
            "object storage bucket. Supports streaming of large files (>10 GB) using PDAL's streaming reader. "
            "Use this as the first node in any processing pipeline that starts from a raw uploaded file."
        ),
        "input_schema": {"s3_key": {"type": "string", "required": True}},
        "output_schema": {"point_cloud": {"type": "object"}},
        "example_params": {"s3_key": "uploads/org_123/survey_456.laz"},
        "tags": ["read", "load", "input", "s3", "r2", "las", "laz", "e57", "ply", "file", "storage", "cloud"],
    },
    {
        "node_type": "pdal.write_copc",
        "display_name": "Write Cloud Optimized Point Cloud (COPC)",
        "category": "io",
        "description": (
            "Convert a point cloud to Cloud Optimized Point Cloud (COPC) format and write it to R2/S3. "
            "COPC is a LAZ file with a clustered octree structure that enables efficient streaming and "
            "progressive loading in web viewers like CesiumJS and Potree. "
            "Use this node after any processing step to make the result viewable in the 3D viewer."
        ),
        "input_schema": {"point_cloud": {"type": "object"}, "output_key": {"type": "string"}},
        "output_schema": {"copc_s3_key": {"type": "string"}, "copc_url": {"type": "string"}},
        "example_params": {"output_key": "processed/org_123/survey_456.copc.laz"},
        "tags": ["write", "save", "output", "copc", "laz", "las", "streaming", "viewer", "cesium", "potree", "web"],
    },
    {
        "node_type": "pdal.filter_noise",
        "display_name": "Remove Statistical Outliers",
        "category": "filter",
        "description": (
            "Remove statistical outlier points from a point cloud using PDAL's StatisticalOutlierRemoval filter. "
            "Points whose mean distance to their k nearest neighbours is more than a specified number of standard "
            "deviations from the global mean are classified as noise and removed. "
            "Use this as the first processing step to clean raw SLAM data before any analysis."
        ),
        "input_schema": {
            "mean_k": {"type": "integer", "default": 8},
            "multiplier": {"type": "number", "default": 3.5},
        },
        "output_schema": {"point_cloud": {"type": "object"}, "removed_count": {"type": "integer"}},
        "example_params": {"mean_k": 8, "multiplier": 3.5},
        "tags": ["filter", "noise", "outlier", "clean", "remove", "statistical", "sor", "pdal", "preprocess"],
    },
    {
        "node_type": "pdal.classify_ground",
        "display_name": "Classify Ground Points (SMRF)",
        "category": "classification",
        "description": (
            "Classify ground vs non-ground points using the Simple Morphological Filter (SMRF) algorithm via PDAL. "
            "Ground points receive ASPRS class code 2; non-ground points receive class 1. "
            "Use this before generating a Digital Terrain Model (DTM) or normalising heights for vegetation analysis."
        ),
        "input_schema": {
            "slope": {"type": "number", "default": 0.15},
            "window": {"type": "number", "default": 18.0},
            "threshold": {"type": "number", "default": 0.5},
        },
        "output_schema": {"point_cloud": {"type": "object"}, "ground_count": {"type": "integer"}},
        "example_params": {"slope": 0.15, "window": 18.0, "threshold": 0.5},
        "tags": ["ground", "classify", "smrf", "terrain", "dtm", "dem", "filter", "pdal", "lidar", "elevation"],
    },
    {
        "node_type": "pdal.generate_dtm",
        "display_name": "Generate Digital Terrain Model (DTM)",
        "category": "analysis",
        "description": (
            "Generate a Digital Terrain Model (DTM) GeoTIFF raster from the ground-classified points in a point cloud "
            "using PDAL's writers.gdal writer. The output is a cloud-optimised GeoTIFF (COG) stored in R2/S3. "
            "Use after the ground classification node to produce a bare-earth elevation model for flood modelling, "
            "road design, or site analysis."
        ),
        "input_schema": {
            "resolution": {"type": "number", "default": 0.5},
            "output_key": {"type": "string"},
        },
        "output_schema": {"dtm_s3_key": {"type": "string"}, "dtm_url": {"type": "string"}},
        "example_params": {"resolution": 0.5, "output_key": "dtm/org_123/survey_456_dtm.tif"},
        "tags": ["dtm", "dem", "terrain", "elevation", "raster", "geotiff", "gdal", "ground", "surface", "model"],
    },
    {
        "node_type": "pdal.georeference",
        "display_name": "Georeference / Reproject Point Cloud",
        "category": "transform",
        "description": (
            "Reproject a point cloud from one coordinate reference system (CRS) to another using PDAL's "
            "filters.reprojection filter (backed by PROJ). "
            "Use this to convert SLAM-captured data in a local or sensor frame into a global geographic CRS "
            "such as WGS84 (EPSG:4326) or a local projected CRS like GDA2020 MGA Zone 55 (EPSG:7855)."
        ),
        "input_schema": {
            "in_srs": {"type": "string", "default": "EPSG:4326"},
            "out_srs": {"type": "string", "default": "EPSG:7855"},
        },
        "output_schema": {"point_cloud": {"type": "object"}},
        "example_params": {"in_srs": "EPSG:4326", "out_srs": "EPSG:7855"},
        "tags": ["georeference", "reproject", "crs", "epsg", "proj", "coordinate", "transform", "wgs84", "gda2020"],
    },
    {
        "node_type": "pdal.colorize",
        "display_name": "Colorize Point Cloud from Imagery",
        "category": "transform",
        "description": (
            "Assign RGB colour values to point cloud points by sampling a co-registered orthophoto or "
            "panoramic image using PDAL's filters.colorization filter. "
            "Use this when the raw SLAM data lacks colour information but a co-registered image is available."
        ),
        "input_schema": {"image_url": {"type": "string", "required": True}},
        "output_schema": {"point_cloud": {"type": "object"}},
        "example_params": {"image_url": "https://example.com/ortho.tif"},
        "tags": ["color", "colour", "rgb", "colorize", "image", "ortho", "texture", "visual", "pdal"],
    },
    {
        "node_type": "ai.road_asset_detection",
        "display_name": "Detect Road Assets (AI)",
        "category": "ai",
        "description": (
            "Use PDAL pipelines and machine learning to automatically detect and classify road infrastructure assets "
            "in a point cloud. Detects: traffic signs (speed limits, stop signs, directional signs), "
            "road markings (lane lines, pedestrian crossings, arrows), stormwater drains and grates, "
            "street light poles, kerb and gutter geometry, and utility pits. "
            "Outputs a GeoJSON FeatureCollection with one feature per detected asset, including class, "
            "confidence score, and 3D centroid coordinates. "
            "Use for road condition surveys, asset inventory management, and infrastructure maintenance planning."
        ),
        "input_schema": {
            "confidence_threshold": {"type": "number", "default": 0.7},
        },
        "output_schema": {
            "road_assets_s3_key": {"type": "string"},
            "road_assets_url": {"type": "string"},
            "asset_count": {"type": "integer"},
        },
        "example_params": {"confidence_threshold": 0.7},
        "tags": [
            "road", "traffic", "sign", "marking", "drain", "detect", "ai", "ml", "classify",
            "infrastructure", "asset", "inventory", "street", "light", "pole", "kerb", "lane",
        ],
    },
    {
        "node_type": "ai.bim_extraction",
        "display_name": "Extract BIM / Floor Plan (AI)",
        "category": "ai",
        "description": (
            "Use Cloud2BIM to segment an indoor point cloud into architectural elements: "
            "walls, floors, ceilings, doors, windows, columns, and stairs. "
            "Outputs an IFC4 file (for import into Revit, ArchiCAD, or Allplan) and a DXF floor plan "
            "(for import into AutoCAD or QGIS). "
            "Use for as-built documentation, building renovation planning, and digital twin creation."
        ),
        "input_schema": {
            "floor_height": {"type": "number", "default": 0.1},
            "ceiling_height": {"type": "number", "default": 2.8},
        },
        "output_schema": {
            "ifc_s3_key": {"type": "string"},
            "dxf_s3_key": {"type": "string"},
        },
        "example_params": {"floor_height": 0.1, "ceiling_height": 2.8},
        "tags": [
            "bim", "ifc", "dxf", "floor plan", "room", "wall", "door", "window", "indoor",
            "building", "cad", "revit", "archicad", "as-built", "digital twin", "architecture",
        ],
    },
    {
        "node_type": "notify.webhook",
        "display_name": "Send Webhook Notification",
        "category": "utility",
        "description": (
            "Send an HTTP POST notification to a webhook URL when the workflow completes or reaches a milestone. "
            "Use to integrate with Slack, Microsoft Teams, PagerDuty, or any custom system. "
            "The payload includes the job status, dataset ID, and any output URLs produced by the workflow."
        ),
        "input_schema": {"url": {"type": "string", "required": True}},
        "output_schema": {"status": {"type": "string"}},
        "example_params": {"url": "https://hooks.example.com/notify"},
        "tags": ["notify", "webhook", "http", "callback", "alert", "complete", "trigger", "slack", "teams"],
    },
    {
        "node_type": "pdal.thin_voxel",
        "display_name": "Voxel Downsample Point Cloud",
        "category": "filter",
        "description": (
            "Reduce point cloud density by keeping one point per voxel cell using PDAL's VoxelGrid filter. "
            "Use to reduce file size and processing time for very dense SLAM scans before analysis. "
            "Typical voxel sizes: 0.05 m for indoor, 0.1–0.5 m for outdoor surveys."
        ),
        "input_schema": {"leaf_size": {"type": "number", "default": 0.1}},
        "output_schema": {"point_cloud": {"type": "object"}, "point_count": {"type": "integer"}},
        "example_params": {"leaf_size": 0.1},
        "tags": ["downsample", "thin", "voxel", "reduce", "density", "grid", "filter", "pdal", "simplify"],
    },
    {
        "node_type": "export.geojson",
        "display_name": "Export Features as GeoJSON",
        "category": "io",
        "description": (
            "Export detected features or classified point cloud segments as a GeoJSON FeatureCollection "
            "and upload to R2/S3. The GeoJSON can be loaded directly into QGIS, Mapbox, Leaflet, or "
            "any standard GIS tool. Use as the final output node when the goal is a 2D map layer."
        ),
        "input_schema": {"output_key": {"type": "string", "required": True}},
        "output_schema": {"geojson_s3_key": {"type": "string"}, "geojson_url": {"type": "string"}},
        "example_params": {"output_key": "exports/org_123/survey_456_features.geojson"},
        "tags": ["export", "geojson", "gis", "map", "qgis", "mapbox", "leaflet", "output", "vector", "features"],
    },
]


def make_embedding_text(node: dict) -> str:
    tags_str = ", ".join(node.get("tags", []))
    return f"{node['display_name']}\n\n{node['description']}\n\nKeywords: {tags_str}"


def get_embeddings_local(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings using a local sentence-transformers model.
    Projects from the model's native dimension to TARGET_DIM using a
    deterministic linear projection (same projection every run).
    """
    print(f"  Loading local model: {LOCAL_MODEL}...")
    model = SentenceTransformer(LOCAL_MODEL)
    native_dim = model.get_sentence_embedding_dimension()
    print(f"  Model native dimension: {native_dim} → projecting to {TARGET_DIM}")

    raw = model.encode(texts, normalize_embeddings=True)  # shape: (N, native_dim)

    # Deterministic projection matrix: seeded so the same texts always produce
    # the same embedding in the DB (important for cosine similarity consistency)
    rng = np.random.default_rng(seed=42)
    projection = rng.standard_normal((native_dim, TARGET_DIM)).astype(np.float32)
    # Normalise columns so the projected vectors remain unit-length
    projection /= np.linalg.norm(projection, axis=0, keepdims=True)

    projected = raw @ projection  # shape: (N, TARGET_DIM)
    # Re-normalise rows after projection
    norms = np.linalg.norm(projected, axis=1, keepdims=True)
    projected = projected / np.maximum(norms, 1e-10)

    return projected.tolist()


def main():
    print(f"Connecting to Supabase: {SUPABASE_URL[:40]}...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print(f"Generating local embeddings for {len(NODE_LIBRARY)} nodes...")
    texts = [make_embedding_text(node) for node in NODE_LIBRARY]
    embeddings = get_embeddings_local(texts)
    print(f"  ✓ Generated {len(embeddings)} embeddings (dim={len(embeddings[0])})")

    print("Upserting nodes into workflow_node_schemas...")
    upserted = 0
    errors = 0
    for node, embedding in zip(NODE_LIBRARY, embeddings):
        row = {
            "node_type": node["node_type"],
            "display_name": node["display_name"],
            "category": node["category"],
            "description": node["description"],
            "input_schema": node["input_schema"],
            "output_schema": node["output_schema"],
            "example_params": node["example_params"],
            "tags": node["tags"],
            "embedding": embedding,
        }
        try:
            supabase.table("workflow_node_schemas").upsert(
                row, on_conflict="node_type"
            ).execute()
            upserted += 1
            print(f"  ✓ {node['node_type']}")
        except Exception as e:
            errors += 1
            print(f"  ✗ {node['node_type']}: {e}")

    print(f"\nDone. {upserted} nodes upserted, {errors} errors.")
    if errors == 0:
        print("Node library is ready for semantic search.")
    else:
        print("Some nodes failed to upsert. Check the errors above.")


if __name__ == "__main__":
    main()
