"""
Generate SQL seed file for workflow_node_schemas.
Produces supabase/seeds/003_node_library.sql with all 12 nodes and their embeddings.

Usage:
    python api/scripts/generate_node_seed_sql.py
"""
from __future__ import annotations
import json
import os
import sys

try:
    from sentence_transformers import SentenceTransformer
    import numpy as np
except ImportError:
    print("ERROR: pip install sentence-transformers numpy")
    sys.exit(1)

LOCAL_MODEL = "all-MiniLM-L6-v2"
TARGET_DIM = 1536

NODE_LIBRARY = [
    {
        "node_type": "pdal.read_s3",
        "display_name": "Read Point Cloud from R2/S3",
        "category": "io",
        "description": "Read a raw point cloud file (LAS, LAZ, E57, or PLY) from Cloudflare R2 or any S3-compatible object storage bucket. Supports streaming of large files (>10 GB) using PDAL's streaming reader. Use this as the first node in any processing pipeline that starts from a raw uploaded file.",
        "input_schema": {"s3_key": {"type": "string", "required": True}},
        "output_schema": {"point_cloud": {"type": "object"}},
        "example_params": {"s3_key": "uploads/org_123/survey_456.laz"},
        "tags": ["read", "load", "input", "s3", "r2", "las", "laz", "e57", "ply", "file", "storage", "cloud"],
    },
    {
        "node_type": "pdal.write_copc",
        "display_name": "Write Cloud Optimized Point Cloud (COPC)",
        "category": "io",
        "description": "Convert a point cloud to Cloud Optimized Point Cloud (COPC) format and write it to R2/S3. COPC is a LAZ file with a clustered octree structure that enables efficient streaming and progressive loading in web viewers like CesiumJS and Potree. Use this node after any processing step to make the result viewable in the 3D viewer.",
        "input_schema": {"point_cloud": {"type": "object"}, "output_key": {"type": "string"}},
        "output_schema": {"copc_s3_key": {"type": "string"}, "copc_url": {"type": "string"}},
        "example_params": {"output_key": "processed/org_123/survey_456.copc.laz"},
        "tags": ["write", "save", "output", "copc", "laz", "las", "streaming", "viewer", "cesium", "potree", "web"],
    },
    {
        "node_type": "pdal.filter_noise",
        "display_name": "Remove Statistical Outliers",
        "category": "filter",
        "description": "Remove statistical outlier points from a point cloud using PDAL's StatisticalOutlierRemoval filter. Points whose mean distance to their k nearest neighbours is more than a specified number of standard deviations from the global mean are classified as noise and removed. Use this as the first processing step to clean raw SLAM data before any analysis.",
        "input_schema": {"mean_k": {"type": "integer", "default": 8}, "multiplier": {"type": "number", "default": 3.5}},
        "output_schema": {"point_cloud": {"type": "object"}, "removed_count": {"type": "integer"}},
        "example_params": {"mean_k": 8, "multiplier": 3.5},
        "tags": ["filter", "noise", "outlier", "clean", "remove", "statistical", "sor", "pdal", "preprocess"],
    },
    {
        "node_type": "pdal.classify_ground",
        "display_name": "Classify Ground Points (SMRF)",
        "category": "classification",
        "description": "Classify ground vs non-ground points using the Simple Morphological Filter (SMRF) algorithm via PDAL. Ground points receive ASPRS class code 2; non-ground points receive class 1. Use this before generating a Digital Terrain Model (DTM) or normalising heights for vegetation analysis.",
        "input_schema": {"slope": {"type": "number", "default": 0.15}, "window": {"type": "number", "default": 18.0}, "threshold": {"type": "number", "default": 0.5}},
        "output_schema": {"point_cloud": {"type": "object"}, "ground_count": {"type": "integer"}},
        "example_params": {"slope": 0.15, "window": 18.0, "threshold": 0.5},
        "tags": ["ground", "classify", "smrf", "terrain", "dtm", "dem", "filter", "pdal", "lidar", "elevation"],
    },
    {
        "node_type": "pdal.generate_dtm",
        "display_name": "Generate Digital Terrain Model (DTM)",
        "category": "analysis",
        "description": "Generate a Digital Terrain Model (DTM) GeoTIFF raster from the ground-classified points in a point cloud using PDAL's writers.gdal writer. The output is a cloud-optimised GeoTIFF (COG) stored in R2/S3. Use after the ground classification node to produce a bare-earth elevation model.",
        "input_schema": {"resolution": {"type": "number", "default": 0.5}, "output_key": {"type": "string"}},
        "output_schema": {"dtm_s3_key": {"type": "string"}, "dtm_url": {"type": "string"}},
        "example_params": {"resolution": 0.5, "output_key": "dtm/org_123/survey_456_dtm.tif"},
        "tags": ["dtm", "dem", "terrain", "elevation", "raster", "geotiff", "gdal", "ground", "surface", "model"],
    },
    {
        "node_type": "pdal.georeference",
        "display_name": "Georeference / Reproject Point Cloud",
        "category": "transform",
        "description": "Reproject a point cloud from one coordinate reference system (CRS) to another using PDAL's filters.reprojection filter (backed by PROJ). Use this to convert SLAM-captured data in a local or sensor frame into a global geographic CRS such as WGS84 (EPSG:4326) or GDA2020 MGA Zone 55 (EPSG:7855).",
        "input_schema": {"in_srs": {"type": "string", "default": "EPSG:4326"}, "out_srs": {"type": "string", "default": "EPSG:7855"}},
        "output_schema": {"point_cloud": {"type": "object"}},
        "example_params": {"in_srs": "EPSG:4326", "out_srs": "EPSG:7855"},
        "tags": ["georeference", "reproject", "crs", "epsg", "proj", "coordinate", "transform", "wgs84", "gda2020"],
    },
    {
        "node_type": "pdal.colorize",
        "display_name": "Colorize Point Cloud from Imagery",
        "category": "transform",
        "description": "Assign RGB colour values to point cloud points by sampling a co-registered orthophoto or panoramic image using PDAL's filters.colorization filter. Use this when the raw SLAM data lacks colour information but a co-registered image is available.",
        "input_schema": {"image_url": {"type": "string", "required": True}},
        "output_schema": {"point_cloud": {"type": "object"}},
        "example_params": {"image_url": "https://example.com/ortho.tif"},
        "tags": ["color", "colour", "rgb", "colorize", "image", "ortho", "texture", "visual", "pdal"],
    },
    {
        "node_type": "ai.road_asset_detection",
        "display_name": "Detect Road Assets (AI)",
        "category": "ai",
        "description": "Use PDAL pipelines and machine learning to automatically detect and classify road infrastructure assets in a point cloud. Detects: traffic signs, road markings, stormwater drains, street light poles, kerb and gutter geometry, and utility pits. Outputs a GeoJSON FeatureCollection with one feature per detected asset.",
        "input_schema": {"confidence_threshold": {"type": "number", "default": 0.7}},
        "output_schema": {"road_assets_s3_key": {"type": "string"}, "road_assets_url": {"type": "string"}, "asset_count": {"type": "integer"}},
        "example_params": {"confidence_threshold": 0.7},
        "tags": ["road", "traffic", "sign", "marking", "drain", "detect", "ai", "ml", "classify", "infrastructure", "asset", "inventory"],
    },
    {
        "node_type": "ai.bim_extraction",
        "display_name": "Extract BIM / Floor Plan (AI)",
        "category": "ai",
        "description": "Use Cloud2BIM to segment an indoor point cloud into architectural elements: walls, floors, ceilings, doors, windows, columns, and stairs. Outputs an IFC4 file and a DXF floor plan. Use for as-built documentation, building renovation planning, and digital twin creation.",
        "input_schema": {"floor_height": {"type": "number", "default": 0.1}, "ceiling_height": {"type": "number", "default": 2.8}},
        "output_schema": {"ifc_s3_key": {"type": "string"}, "dxf_s3_key": {"type": "string"}},
        "example_params": {"floor_height": 0.1, "ceiling_height": 2.8},
        "tags": ["bim", "ifc", "dxf", "floor plan", "room", "wall", "door", "window", "indoor", "building", "cad", "revit", "archicad"],
    },
    {
        "node_type": "notify.webhook",
        "display_name": "Send Webhook Notification",
        "category": "utility",
        "description": "Send an HTTP POST notification to a webhook URL when the workflow completes or reaches a milestone. Use to integrate with Slack, Microsoft Teams, PagerDuty, or any custom system.",
        "input_schema": {"url": {"type": "string", "required": True}},
        "output_schema": {"status": {"type": "string"}},
        "example_params": {"url": "https://hooks.example.com/notify"},
        "tags": ["notify", "webhook", "http", "callback", "alert", "complete", "trigger", "slack", "teams"],
    },
    {
        "node_type": "pdal.thin_voxel",
        "display_name": "Voxel Downsample Point Cloud",
        "category": "filter",
        "description": "Reduce point cloud density by keeping one point per voxel cell using PDAL's VoxelGrid filter. Use to reduce file size and processing time for very dense SLAM scans before analysis.",
        "input_schema": {"leaf_size": {"type": "number", "default": 0.1}},
        "output_schema": {"point_cloud": {"type": "object"}, "point_count": {"type": "integer"}},
        "example_params": {"leaf_size": 0.1},
        "tags": ["downsample", "thin", "voxel", "reduce", "density", "grid", "filter", "pdal", "simplify"],
    },
    {
        "node_type": "export.geojson",
        "display_name": "Export Features as GeoJSON",
        "category": "io",
        "description": "Export detected features or classified point cloud segments as a GeoJSON FeatureCollection and upload to R2/S3. The GeoJSON can be loaded directly into QGIS, Mapbox, Leaflet, or any standard GIS tool.",
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
    model = SentenceTransformer(LOCAL_MODEL)
    native_dim = model.get_sentence_embedding_dimension()
    raw = model.encode(texts, normalize_embeddings=True)
    rng = np.random.default_rng(seed=42)
    projection = rng.standard_normal((native_dim, TARGET_DIM)).astype(np.float32)
    projection /= np.linalg.norm(projection, axis=0, keepdims=True)
    projected = raw @ projection
    norms = np.linalg.norm(projected, axis=1, keepdims=True)
    projected = projected / np.maximum(norms, 1e-10)
    return projected.tolist()


def escape_sql_string(s: str) -> str:
    return s.replace("'", "''")


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "../../supabase/seeds")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "003_node_library.sql")

    print(f"Generating embeddings for {len(NODE_LIBRARY)} nodes...")
    texts = [make_embedding_text(node) for node in NODE_LIBRARY]
    embeddings = get_embeddings_local(texts)
    print(f"  ✓ {len(embeddings)} embeddings (dim={len(embeddings[0])})")

    lines = [
        "-- Auto-generated by api/scripts/generate_node_seed_sql.py",
        "-- Run this in the Supabase SQL editor or via supabase db push",
        "-- Embeddings use all-MiniLM-L6-v2 projected to 1536 dims (seed=42)",
        "",
        "INSERT INTO public.workflow_node_schemas",
        "  (node_type, display_name, category, description, input_schema, output_schema, example_params, tags, embedding)",
        "VALUES",
    ]

    rows = []
    for node, emb in zip(NODE_LIBRARY, embeddings):
        emb_str = "[" + ",".join(f"{v:.8f}" for v in emb) + "]"
        row = (
            f"  ('{escape_sql_string(node['node_type'])}', "
            f"'{escape_sql_string(node['display_name'])}', "
            f"'{escape_sql_string(node['category'])}', "
            f"'{escape_sql_string(node['description'])}', "
            f"'{escape_sql_string(json.dumps(node['input_schema']))}', "
            f"'{escape_sql_string(json.dumps(node['output_schema']))}', "
            f"'{escape_sql_string(json.dumps(node['example_params']))}', "
            f"ARRAY{json.dumps(node['tags'])}::text[], "
            f"'{emb_str}'::vector)"
        )
        rows.append(row)

    lines.append(",\n".join(rows))
    lines.append("ON CONFLICT (node_type) DO UPDATE SET")
    lines.append("  display_name = EXCLUDED.display_name,")
    lines.append("  description = EXCLUDED.description,")
    lines.append("  input_schema = EXCLUDED.input_schema,")
    lines.append("  output_schema = EXCLUDED.output_schema,")
    lines.append("  example_params = EXCLUDED.example_params,")
    lines.append("  tags = EXCLUDED.tags,")
    lines.append("  embedding = EXCLUDED.embedding;")
    lines.append("")

    with open(out_path, "w") as f:
        f.write("\n".join(lines))

    print(f"  ✓ SQL seed written to: {out_path}")
    print(f"  Run it in the Supabase SQL editor or via: supabase db push")


if __name__ == "__main__":
    main()
