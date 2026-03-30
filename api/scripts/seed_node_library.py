"""
Node Library Seed Script
========================
Populates the workflow_node_schemas table with embeddings so the LangGraph
agent's node_selector step can perform pgvector semantic search.

Usage:
    python api/scripts/seed_node_library.py

Requirements:
    - SUPABASE_URL and SUPABASE_SERVICE_KEY env vars set
    - OPENAI_API_KEY env var set (used for text-embedding-3-small)
    - pip install supabase openai

The script is idempotent: it upserts on node_type so it is safe to re-run
after adding new nodes or updating descriptions.
"""
from __future__ import annotations

import os
import sys
import json
import time

# ── Dependency check ──────────────────────────────────────────────────────────
try:
    from supabase import create_client, Client
    from openai import OpenAI
except ImportError:
    print("ERROR: Missing dependencies. Run: pip install supabase openai")
    sys.exit(1)

# ── Configuration ─────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", os.environ.get("SUPABASE_ANON_KEY", ""))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    sys.exit(1)

if not OPENAI_API_KEY:
    print("ERROR: OPENAI_API_KEY must be set")
    sys.exit(1)

# ── Node library definition ───────────────────────────────────────────────────
# Each node is described with enough natural-language context so that the
# agent's semantic search can find the right node for any user request.

NODE_LIBRARY = [
    # ── Point Cloud I/O ──────────────────────────────────────────────────────
    {
        "node_type": "pdal.read_s3",
        "display_name": "Read Point Cloud from S3",
        "category": "point_cloud",
        "description": (
            "Read a LAS, LAZ, or COPC point cloud file from an S3-compatible object storage bucket "
            "into the processing pipeline. Supports Cloudflare R2, AWS S3, and MinIO. "
            "Use this as the first step in any point cloud processing workflow."
        ),
        "input_schema": {"s3_key": {"type": "string", "required": True}},
        "output_schema": {"point_cloud": {"type": "pdal_pipeline"}},
        "example_params": {"s3_key": "datasets/abc123/raw.laz"},
        "tags": ["read", "input", "s3", "las", "laz", "copc", "load", "import"],
    },
    {
        "node_type": "pdal.write_copc",
        "display_name": "Write COPC (Cloud Optimized Point Cloud)",
        "category": "point_cloud",
        "description": (
            "Write the processed point cloud to COPC LAZ format on S3 for web streaming. "
            "COPC is the modern cloud-native format that enables direct streaming in browsers "
            "using CesiumJS and Potree without a tile server. Use this as the final step "
            "in any processing pipeline that needs to be visualised in the 3D viewer."
        ),
        "input_schema": {"s3_key": {"type": "string", "required": True}},
        "output_schema": {"s3_key": {"type": "string"}, "copc_url": {"type": "string"}},
        "example_params": {"s3_key": "datasets/abc123/processed.copc.laz"},
        "tags": ["write", "output", "copc", "laz", "s3", "stream", "tile", "publish", "export"],
    },
    # ── Filtering & Cleaning ─────────────────────────────────────────────────
    {
        "node_type": "pdal.noise_remove",
        "display_name": "Remove Noise Points",
        "category": "point_cloud",
        "description": (
            "Remove statistical outlier noise points using k-nearest neighbour analysis. "
            "Eliminates stray points caused by sensor noise, multipath reflections, or "
            "moving objects (vehicles, pedestrians) during mobile mapping surveys. "
            "Apply before any classification or detection step."
        ),
        "input_schema": {
            "mean_k": {"type": "integer", "default": 8},
            "multiplier": {"type": "number", "default": 2.0},
        },
        "output_schema": {"point_cloud": {"type": "pdal_pipeline"}},
        "example_params": {"mean_k": 8, "multiplier": 2.0},
        "tags": ["noise", "outlier", "clean", "filter", "statistical", "knn", "denoise", "remove"],
    },
    {
        "node_type": "pdal.crop",
        "display_name": "Crop / Clip Point Cloud",
        "category": "point_cloud",
        "description": (
            "Clip a point cloud to a bounding box or polygon geometry, removing all points "
            "outside the boundary. Use to extract a region of interest from a large survey, "
            "or to restrict processing to a specific area such as a road corridor or building footprint."
        ),
        "input_schema": {"bounds": {"type": "string"}},
        "output_schema": {"point_cloud": {"type": "pdal_pipeline"}},
        "example_params": {"bounds": "([0,100],[0,100],[0,50])"},
        "tags": ["crop", "clip", "filter", "boundary", "polygon", "bbox", "area", "subset", "extract"],
    },
    {
        "node_type": "pdal.decimate",
        "display_name": "Decimate / Thin Point Cloud",
        "category": "point_cloud",
        "description": (
            "Reduce point cloud density by keeping every Nth point or using voxel grid subsampling. "
            "Use to speed up downstream processing, reduce file size, or create a lightweight "
            "preview version of a dense survey. Voxel grid subsampling preserves spatial distribution "
            "better than simple every-Nth decimation."
        ),
        "input_schema": {
            "step": {"type": "integer", "default": 10},
            "method": {"type": "string", "default": "every_nth"},
        },
        "output_schema": {"point_cloud": {"type": "pdal_pipeline"}},
        "example_params": {"step": 10},
        "tags": ["decimate", "thin", "downsample", "reduce", "density", "voxel", "subsample", "simplify"],
    },
    # ── Classification ───────────────────────────────────────────────────────
    {
        "node_type": "pdal.ground_classify",
        "display_name": "Classify Ground Points",
        "category": "point_cloud",
        "description": (
            "Identify and classify ground points using the SMRF (Simple Morphological Filter) algorithm. "
            "Ground classification is required before generating a Digital Terrain Model (DTM) or "
            "normalising the point cloud height. Works on both aerial LiDAR and mobile mapping data."
        ),
        "input_schema": {
            "slope": {"type": "number", "default": 0.15},
            "window": {"type": "number", "default": 18},
        },
        "output_schema": {"point_cloud": {"type": "pdal_pipeline"}},
        "example_params": {"slope": 0.15, "window": 18},
        "tags": ["ground", "classify", "smrf", "dtm", "terrain", "filter", "lidar", "classification"],
    },
    # ── Terrain & Raster ─────────────────────────────────────────────────────
    {
        "node_type": "pdal.dtm",
        "display_name": "Generate DTM Raster",
        "category": "point_cloud",
        "description": (
            "Generate a Digital Terrain Model (DTM) GeoTIFF raster from classified ground points. "
            "The DTM represents the bare earth surface without vegetation or structures. "
            "Requires ground classification to have been run first. "
            "Output is a GeoTIFF stored on S3 at the specified resolution."
        ),
        "input_schema": {"resolution": {"type": "number", "default": 0.5}},
        "output_schema": {"geotiff_s3_key": {"type": "string"}},
        "example_params": {"resolution": 0.5},
        "tags": ["dtm", "dem", "terrain", "raster", "geotiff", "elevation", "ground", "surface", "height model"],
    },
    # ── Coordinate Reference System ──────────────────────────────────────────
    {
        "node_type": "pdal.reproject",
        "display_name": "Reproject / Transform CRS",
        "category": "point_cloud",
        "description": (
            "Reproject point cloud coordinates from one coordinate reference system to another using PROJ. "
            "Use to convert between projected systems (e.g. MGA2020 to WGS84) or to align a dataset "
            "with a known geographic reference frame. Required when combining datasets from different sources."
        ),
        "input_schema": {
            "in_srs": {"type": "string", "required": True},
            "out_srs": {"type": "string", "required": True},
        },
        "output_schema": {"point_cloud": {"type": "pdal_pipeline"}},
        "example_params": {"in_srs": "EPSG:32755", "out_srs": "EPSG:4326"},
        "tags": ["reproject", "crs", "coordinate", "transform", "epsg", "proj", "georeference", "wgs84", "mga"],
    },
    {
        "node_type": "geo.georeference",
        "display_name": "Georeference with GCPs",
        "category": "point_cloud",
        "description": (
            "Apply ground control points (GCPs) to georeference a SLAM or unregistered point cloud "
            "using a rubber-sheeting transformation (TPS or affine). "
            "Use when a point cloud was captured without GPS and needs to be aligned to a known coordinate system. "
            "GCPs must be provided as pairs of source (scanner) and target (world) coordinates."
        ),
        "input_schema": {
            "gcps": {"type": "array"},
            "method": {"type": "string", "default": "tps"},
        },
        "output_schema": {"point_cloud": {"type": "pdal_pipeline"}},
        "example_params": {
            "gcps": [{"source": [10.5, 20.3, 1.2], "target": [151.2093, -33.8688, 45.0]}],
            "method": "tps",
        },
        "tags": ["georeference", "gcp", "control point", "slam", "transform", "coordinate", "align", "register", "icp"],
    },
    # ── AI / ML Detection ────────────────────────────────────────────────────
    {
        "node_type": "ai.road_assets",
        "display_name": "Detect Road Assets (AI)",
        "category": "ai",
        "description": (
            "Use AI-powered 3D object detection to automatically find and classify road infrastructure assets "
            "including traffic signs, road markings, lane lines, kerbs, drains, street lights, and poles. "
            "Returns a GeoJSON FeatureCollection with one feature per detected asset, including "
            "asset type, confidence score, height, and bounding box. "
            "Use for road condition surveys, asset inventory, and infrastructure management."
        ),
        "input_schema": {
            "confidence_threshold": {"type": "number", "default": 0.7},
        },
        "output_schema": {
            "geojson_s3_key": {"type": "string"},
            "feature_count": {"type": "integer"},
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
    # ── Utility ──────────────────────────────────────────────────────────────
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
]


# ── Embedding generation ──────────────────────────────────────────────────────

def make_embedding_text(node: dict) -> str:
    """
    Constructs the text to embed for a node.
    Combines display_name, description, and tags for rich semantic coverage.
    """
    tags_str = ", ".join(node.get("tags", []))
    return f"{node['display_name']}\n\n{node['description']}\n\nKeywords: {tags_str}"


def get_embeddings(texts: list[str], client: OpenAI) -> list[list[float]]:
    """Batch-embeds a list of texts using the OpenAI embedding API."""
    embeddings = []
    batch_size = 20
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        embeddings.extend([item.embedding for item in response.data])
        if i + batch_size < len(texts):
            time.sleep(0.5)  # Rate limit courtesy pause
    return embeddings


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Connecting to Supabase: {SUPABASE_URL[:40]}...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    openai_client = OpenAI(api_key=OPENAI_API_KEY)

    print(f"Generating embeddings for {len(NODE_LIBRARY)} nodes using {EMBEDDING_MODEL}...")
    texts = [make_embedding_text(node) for node in NODE_LIBRARY]
    embeddings = get_embeddings(texts, openai_client)
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
