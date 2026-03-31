"""
Push the node library seed to Supabase using the Management API /database/query endpoint.
This bypasses the need for direct PostgreSQL connectivity.

Usage:
    OPENAI_API_KEY=sk-... python api/scripts/push_seed_via_api.py
"""
from __future__ import annotations
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

try:
    from openai import OpenAI
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "openai", "-q"])
    from openai import OpenAI

SUPABASE_ACCESS_TOKEN = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
PROJECT_REF = os.environ.get("SUPABASE_PROJECT_REF", "bfazarpbdrppywnofvfj")
MGMT_API_BASE = f"https://api.supabase.com/v1/projects/{PROJECT_REF}"

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
EMBEDDING_MODEL = "text-embedding-3-small"

NODE_LIBRARY = [
    {
        "node_type": "pdal.read_s3",
        "display_name": "Read Point Cloud from S3",
        "category": "point_cloud",
        "description": "Read a raw point cloud file (LAS, LAZ, E57, or PLY) from Cloudflare R2 or any S3-compatible object storage bucket. Supports streaming of large files (>10 GB) using PDAL's streaming reader. Use this as the first node in any processing pipeline that starts from a raw uploaded file.",
        "input_schema": {"s3_key": {"type": "string", "required": True}},
        "output_schema": {"point_cloud": {"type": "object"}},
        "example_params": {"s3_key": "uploads/org_123/survey_456.laz"},
        "tags": ["read", "load", "input", "s3", "r2", "las", "laz", "e57", "ply", "file", "storage", "cloud"],
    },
    {
        "node_type": "pdal.write_copc",
        "display_name": "Write COPC (Cloud Optimized Point Cloud)",
        "category": "point_cloud",
        "description": "Convert a point cloud to Cloud Optimized Point Cloud (COPC) format and write it to R2/S3. COPC is a LAZ file with a clustered octree structure that enables efficient streaming and progressive loading in web viewers like CesiumJS and Potree. Use this node after any processing step to make the result viewable in the 3D viewer.",
        "input_schema": {"point_cloud": {"type": "object"}, "output_key": {"type": "string"}},
        "output_schema": {"copc_s3_key": {"type": "string"}, "copc_url": {"type": "string"}},
        "example_params": {"output_key": "processed/org_123/survey_456.copc.laz"},
        "tags": ["write", "save", "output", "copc", "laz", "las", "streaming", "viewer", "cesium", "potree", "web"],
    },
    {
        "node_type": "pdal.noise_remove",
        "display_name": "Remove Noise Points",
        "category": "point_cloud",
        "description": "Remove statistical outlier points from a point cloud using PDAL's StatisticalOutlierRemoval filter. Points whose mean distance to their k nearest neighbours is more than a specified number of standard deviations from the global mean are classified as noise and removed. Use this as the first processing step to clean raw SLAM data before any analysis.",
        "input_schema": {"mean_k": {"type": "integer", "default": 8}, "multiplier": {"type": "number", "default": 3.5}},
        "output_schema": {"point_cloud": {"type": "object"}, "removed_count": {"type": "integer"}},
        "example_params": {"mean_k": 8, "multiplier": 3.5},
        "tags": ["filter", "noise", "outlier", "clean", "remove", "statistical", "sor", "pdal", "preprocess"],
    },
    {
        "node_type": "pdal.crop",
        "display_name": "Crop / Clip Point Cloud",
        "category": "point_cloud",
        "description": "Crop a point cloud to a bounding box or polygon boundary using PDAL's filters.crop filter. Use to isolate a region of interest from a large survey, or to clip to a cadastral boundary before delivering to a client.",
        "input_schema": {"bounds": {"type": "string", "description": "WKT polygon or bbox [minx,miny,maxx,maxy]"}},
        "output_schema": {"point_cloud": {"type": "object"}, "point_count": {"type": "integer"}},
        "example_params": {"bounds": "([151.2, -33.9, 151.3, -33.8])"},
        "tags": ["crop", "clip", "cut", "boundary", "bbox", "polygon", "region", "filter", "pdal"],
    },
    {
        "node_type": "pdal.decimate",
        "display_name": "Decimate / Thin Point Cloud",
        "category": "point_cloud",
        "description": "Reduce point cloud density by keeping one point per voxel cell using PDAL's VoxelGrid filter. Use to reduce file size and processing time for very dense SLAM scans before analysis. Typical voxel sizes: 0.05 m for indoor, 0.1–0.5 m for outdoor surveys.",
        "input_schema": {"leaf_size": {"type": "number", "default": 0.1}},
        "output_schema": {"point_cloud": {"type": "object"}, "point_count": {"type": "integer"}},
        "example_params": {"leaf_size": 0.1},
        "tags": ["downsample", "thin", "voxel", "reduce", "density", "grid", "filter", "pdal", "simplify", "decimate"],
    },
    {
        "node_type": "pdal.ground_classify",
        "display_name": "Classify Ground Points",
        "category": "point_cloud",
        "description": "Classify ground vs non-ground points using the Simple Morphological Filter (SMRF) algorithm via PDAL. Ground points receive ASPRS class code 2; non-ground points receive class 1. Use this before generating a Digital Terrain Model (DTM) or normalising heights for vegetation analysis.",
        "input_schema": {"slope": {"type": "number", "default": 0.15}, "window": {"type": "number", "default": 18.0}, "threshold": {"type": "number", "default": 0.5}},
        "output_schema": {"point_cloud": {"type": "object"}, "ground_count": {"type": "integer"}},
        "example_params": {"slope": 0.15, "window": 18.0, "threshold": 0.5},
        "tags": ["ground", "classify", "smrf", "terrain", "dtm", "dem", "filter", "pdal", "lidar", "elevation"],
    },
    {
        "node_type": "pdal.dtm",
        "display_name": "Generate DTM Raster",
        "category": "point_cloud",
        "description": "Generate a Digital Terrain Model (DTM) GeoTIFF raster from the ground-classified points in a point cloud using PDAL's writers.gdal writer. The output is a cloud-optimised GeoTIFF (COG) stored in R2/S3. Use after the ground classification node to produce a bare-earth elevation model for flood modelling, road design, or site analysis.",
        "input_schema": {"resolution": {"type": "number", "default": 0.5}, "output_key": {"type": "string"}},
        "output_schema": {"dtm_s3_key": {"type": "string"}, "dtm_url": {"type": "string"}},
        "example_params": {"resolution": 0.5, "output_key": "dtm/org_123/survey_456_dtm.tif"},
        "tags": ["dtm", "dem", "terrain", "elevation", "raster", "geotiff", "gdal", "ground", "surface", "model"],
    },
    {
        "node_type": "pdal.reproject",
        "display_name": "Reproject / Transform CRS",
        "category": "point_cloud",
        "description": "Reproject a point cloud from one coordinate reference system (CRS) to another using PDAL's filters.reprojection filter (backed by PROJ). Use this to convert SLAM-captured data in a local or sensor frame into a global geographic CRS such as WGS84 (EPSG:4326) or GDA2020 MGA Zone 55 (EPSG:7855).",
        "input_schema": {"in_srs": {"type": "string", "default": "EPSG:4326"}, "out_srs": {"type": "string", "default": "EPSG:7855"}},
        "output_schema": {"point_cloud": {"type": "object"}},
        "example_params": {"in_srs": "EPSG:4326", "out_srs": "EPSG:7855"},
        "tags": ["georeference", "reproject", "crs", "epsg", "proj", "coordinate", "transform", "wgs84", "gda2020"],
    },
    {
        "node_type": "geo.georeference",
        "display_name": "Georeference with GCPs",
        "category": "point_cloud",
        "description": "Georeference a point cloud using Ground Control Points (GCPs) to align it to a known coordinate reference system. Use when the raw SLAM data is in a local or arbitrary frame and you have surveyed GCP coordinates to anchor it to the real world.",
        "input_schema": {"gcps": {"type": "array", "description": "List of {local: [x,y,z], world: [lon,lat,elev]} GCP pairs"}},
        "output_schema": {"point_cloud": {"type": "object"}, "rmse": {"type": "number"}},
        "example_params": {"gcps": [{"local": [0, 0, 0], "world": [151.2, -33.8, 10.0]}]},
        "tags": ["georeference", "gcp", "control", "align", "survey", "coordinate", "transform", "anchor"],
    },
    {
        "node_type": "ai.road_assets",
        "display_name": "Detect Road Assets (AI)",
        "category": "ai",
        "description": "Use PDAL pipelines and machine learning to automatically detect and classify road infrastructure assets in a point cloud. Detects: traffic signs, road markings, stormwater drains, street light poles, kerb and gutter geometry, and utility pits. Outputs a GeoJSON FeatureCollection with one feature per detected asset, including class, confidence score, and 3D centroid coordinates.",
        "input_schema": {"confidence_threshold": {"type": "number", "default": 0.7}},
        "output_schema": {"road_assets_s3_key": {"type": "string"}, "road_assets_url": {"type": "string"}, "asset_count": {"type": "integer"}},
        "example_params": {"confidence_threshold": 0.7},
        "tags": ["road", "traffic", "sign", "marking", "drain", "detect", "ai", "ml", "classify", "infrastructure", "asset", "inventory", "street", "light", "pole", "kerb", "lane"],
    },
    {
        "node_type": "ai.bim_extraction",
        "display_name": "Extract BIM / Floor Plan (AI)",
        "category": "ai",
        "description": "Use Cloud2BIM to segment an indoor point cloud into architectural elements: walls, floors, ceilings, doors, windows, columns, and stairs. Outputs an IFC4 file (for import into Revit, ArchiCAD, or Allplan) and a DXF floor plan (for import into AutoCAD or QGIS). Use for as-built documentation, building renovation planning, and digital twin creation.",
        "input_schema": {"floor_height": {"type": "number", "default": 0.1}, "ceiling_height": {"type": "number", "default": 2.8}},
        "output_schema": {"ifc_s3_key": {"type": "string"}, "dxf_s3_key": {"type": "string"}},
        "example_params": {"floor_height": 0.1, "ceiling_height": 2.8},
        "tags": ["bim", "ifc", "dxf", "floor plan", "room", "wall", "door", "window", "indoor", "building", "cad", "revit", "archicad", "as-built", "digital twin", "architecture"],
    },
    {
        "node_type": "notify.webhook",
        "display_name": "Send Webhook Notification",
        "category": "utility",
        "description": "Send an HTTP POST notification to a webhook URL when the workflow completes or reaches a milestone. Use to integrate with Slack, Microsoft Teams, PagerDuty, or any custom system. The payload includes the job status, dataset ID, and any output URLs produced by the workflow.",
        "input_schema": {"url": {"type": "string", "required": True}},
        "output_schema": {"status": {"type": "string"}},
        "example_params": {"url": "https://hooks.example.com/notify"},
        "tags": ["notify", "webhook", "http", "callback", "alert", "complete", "trigger", "slack", "teams"],
    },
]


def run_query(sql: str) -> list:
    resp = requests.post(
        f"{MGMT_API_BASE}/database/query",
        headers={
            "Authorization": f"Bearer {SUPABASE_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"query": sql},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def make_embedding_text(node: dict) -> str:
    tags_str = ", ".join(node.get("tags", []))
    return f"{node['display_name']}\n\n{node['description']}\n\nKeywords: {tags_str}"


def main():
    print(f"Generating {EMBEDDING_MODEL} embeddings for {len(NODE_LIBRARY)} nodes...")
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    texts = [make_embedding_text(n) for n in NODE_LIBRARY]
    resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    embeddings = [item.embedding for item in resp.data]
    print(f"  ✓ {len(embeddings)} embeddings (dim={len(embeddings[0])})")

    print(f"\nUpserting {len(NODE_LIBRARY)} nodes via Management API...")
    ok = 0
    errors = 0
    for node, emb in zip(NODE_LIBRARY, embeddings):
        emb_str = "[" + ",".join(f"{v:.8f}" for v in emb) + "]"

        def esc(s: str) -> str:
            return s.replace("'", "''")

        # Build a SQL-safe single-quoted array literal: ARRAY['tag1','tag2']::text[]
        tags_sql = "ARRAY[" + ",".join(f"'{t.replace(chr(39), chr(39)+chr(39))}'" for t in node["tags"]) + "]::text[]"
        sql = f"""
INSERT INTO public.workflow_node_schemas
  (node_type, display_name, category, description, input_schema, output_schema, example_params, tags, embedding)
VALUES (
  '{esc(node["node_type"])}',
  '{esc(node["display_name"])}',
  '{esc(node["category"])}',
  '{esc(node["description"])}',
  '{esc(json.dumps(node["input_schema"]))}',
  '{esc(json.dumps(node["output_schema"]))}',
  '{esc(json.dumps(node["example_params"]))}',
  {tags_sql},
  '{emb_str}'::vector
)
ON CONFLICT (node_type) DO UPDATE SET
  display_name   = EXCLUDED.display_name,
  category       = EXCLUDED.category,
  description    = EXCLUDED.description,
  input_schema   = EXCLUDED.input_schema,
  output_schema  = EXCLUDED.output_schema,
  example_params = EXCLUDED.example_params,
  tags           = EXCLUDED.tags,
  embedding      = EXCLUDED.embedding;
"""
        try:
            run_query(sql)
            print(f"  ✓ {node['node_type']}")
            ok += 1
        except Exception as e:
            print(f"  ✗ {node['node_type']}: {e}")
            errors += 1
        time.sleep(0.1)  # be gentle with the API

    print(f"\nDone. {ok} nodes upserted, {errors} errors.")

    # Verify
    rows = run_query(
        "SELECT node_type, CASE WHEN embedding IS NULL THEN 'no embedding' ELSE 'has embedding' END AS emb_status "
        "FROM workflow_node_schemas ORDER BY node_type"
    )
    print("\nVerification:")
    for r in rows:
        print(f"  {r['node_type']}: {r['emb_status']}")


if __name__ == "__main__":
    main()
