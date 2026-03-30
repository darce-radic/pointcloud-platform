"""
STAC Data Catalogue Router
Implements the SpatioTemporal Asset Catalog (STAC) API Specification v1.0.0
as a translation layer over the Supabase `datasets` and `projects` tables.

Mapping:
  STAC Catalog    → platform root
  STAC Collection → projects table row
  STAC Item       → datasets table row
  STAC Assets     → copc_url, raw_s3_key, ifc_url, road_assets_url columns

Endpoints:
  GET  /stac                                    — Root catalog
  GET  /stac/collections                        — All collections (projects)
  GET  /stac/collections/{collection_id}        — Single collection
  GET  /stac/collections/{collection_id}/items  — Items in a collection
  GET  /stac/search                             — Spatial/temporal item search
  POST /stac/search                             — Same, with JSON body
"""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from supabase import Client

from config import settings
from dependencies import get_current_user, get_supabase, AuthenticatedUser

router = APIRouter(prefix="/stac", tags=["STAC Catalogue"])

# ── Helpers ───────────────────────────────────────────────────────────────────

def _self_url(request: Request, path: str = "") -> str:
    """Build an absolute URL relative to the API root."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/stac{path}"


def _project_to_collection(project: dict, request: Request) -> dict:
    """Convert a Supabase project row to a STAC Collection object."""
    col_id = project["id"]
    return {
        "type": "Collection",
        "id": col_id,
        "stac_version": "1.0.0",
        "title": project.get("name", col_id),
        "description": project.get("description") or f"Point cloud datasets for project {project.get('name', col_id)}",
        "license": "proprietary",
        "extent": {
            "spatial": {"bbox": [[-180, -90, 180, 90]]},
            "temporal": {"interval": [[project.get("created_at"), None]]},
        },
        "links": [
            {"rel": "self", "href": _self_url(request, f"/collections/{col_id}"), "type": "application/json"},
            {"rel": "root", "href": _self_url(request), "type": "application/json"},
            {"rel": "items", "href": _self_url(request, f"/collections/{col_id}/items"), "type": "application/geo+json"},
        ],
    }


def _dataset_to_item(dataset: dict, request: Request) -> dict:
    """Convert a Supabase dataset row to a STAC Item (GeoJSON Feature)."""
    ds_id = dataset["id"]
    project_id = dataset.get("project_id", "")

    # Geometry: use bbox_geom if available (PostGIS GeoJSON), else null
    geometry = None
    bbox_raw = dataset.get("bbox_geom")
    if bbox_raw:
        try:
            geometry = json.loads(bbox_raw) if isinstance(bbox_raw, str) else bbox_raw
        except (json.JSONDecodeError, TypeError):
            geometry = None

    # Derive a flat bbox array from the geometry envelope when possible
    bbox: Optional[list[float]] = None
    if geometry and geometry.get("type") == "Polygon":
        try:
            coords = [c for ring in geometry["coordinates"] for c in ring]
            lons = [c[0] for c in coords]
            lats = [c[1] for c in coords]
            bbox = [min(lons), min(lats), max(lons), max(lats)]
        except (KeyError, IndexError, TypeError):
            bbox = None

    # Datetime: prefer capture_date, fall back to created_at
    dt = dataset.get("capture_date") or dataset.get("created_at")

    # Assets
    assets: dict[str, Any] = {}
    if dataset.get("copc_url"):
        assets["copc"] = {
            "href": dataset["copc_url"],
            "type": "application/vnd.las",
            "title": "Cloud Optimized Point Cloud (COPC)",
            "roles": ["data"],
        }
    if dataset.get("raw_s3_key"):
        raw_url = f"{settings.R2_PUBLIC_BASE}/{dataset['raw_s3_key']}" if settings.R2_PUBLIC_BASE else dataset["raw_s3_key"]
        assets["raw"] = {
            "href": raw_url,
            "type": "application/octet-stream",
            "title": "Raw point cloud file",
            "roles": ["data"],
        }
    if dataset.get("ifc_url"):
        assets["ifc"] = {
            "href": dataset["ifc_url"],
            "type": "application/x-step",
            "title": "IFC4 BIM model",
            "roles": ["derived_data"],
        }
    if dataset.get("road_assets_url"):
        assets["road_assets"] = {
            "href": dataset["road_assets_url"],
            "type": "application/geo+json",
            "title": "Detected road assets (GeoJSON)",
            "roles": ["derived_data"],
        }
    if dataset.get("dtm_url"):
        assets["dtm"] = {
            "href": dataset["dtm_url"],
            "type": "image/tiff; application=geotiff",
            "title": "Digital Terrain Model (GeoTIFF)",
            "roles": ["derived_data"],
        }

    item: dict[str, Any] = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "stac_extensions": [],
        "id": ds_id,
        "geometry": geometry,
        "properties": {
            "datetime": dt,
            "title": dataset.get("name", ds_id),
            "description": dataset.get("description"),
            "point_count": dataset.get("point_count"),
            "crs_epsg": dataset.get("crs_epsg"),
            "processing_status": dataset.get("processing_status"),
            "capture_date": dataset.get("capture_date"),
            "created_at": dataset.get("created_at"),
        },
        "assets": assets,
        "links": [
            {"rel": "self", "href": _self_url(request, f"/collections/{project_id}/items/{ds_id}"), "type": "application/geo+json"},
            {"rel": "root", "href": _self_url(request), "type": "application/json"},
            {"rel": "collection", "href": _self_url(request, f"/collections/{project_id}"), "type": "application/json"},
        ],
        "collection": project_id,
    }

    if bbox:
        item["bbox"] = bbox

    return item


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", summary="STAC Root Catalog")
async def stac_root(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Return the STAC root catalog listing all collections the user can access."""
    projects = (
        supabase.table("projects")
        .select("id, name")
        .eq("organization_id", user.organization_id)
        .execute()
    )

    collection_links = []
    for p in (projects.data or []):
        collection_links.append({
            "rel": "child",
            "href": _self_url(request, f"/collections/{p['id']}"),
            "type": "application/json",
            "title": p.get("name", p["id"]),
        })

    return {
        "type": "Catalog",
        "id": "pointcloud-platform",
        "stac_version": "1.0.0",
        "title": "PointCloud Platform STAC Catalogue",
        "description": (
            "SpatioTemporal Asset Catalog for SLAM-captured point cloud surveys. "
            "Supports georeferencing, BIM extraction, and road asset detection."
        ),
        "conformsTo": [
            "https://api.stacspec.org/v1.0.0/core",
            "https://api.stacspec.org/v1.0.0/item-search",
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
        ],
        "links": [
            {"rel": "self", "href": _self_url(request), "type": "application/json"},
            {"rel": "root", "href": _self_url(request), "type": "application/json"},
            {"rel": "collections", "href": _self_url(request, "/collections"), "type": "application/json"},
            {"rel": "search", "href": _self_url(request, "/search"), "type": "application/geo+json", "method": "GET"},
            {"rel": "search", "href": _self_url(request, "/search"), "type": "application/geo+json", "method": "POST"},
            *collection_links,
        ],
    }


@router.get("/collections", summary="List STAC Collections (projects)")
async def list_collections(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Return all STAC Collections (projects) the user has access to."""
    result = (
        supabase.table("projects")
        .select("id, name, description, created_at")
        .eq("organization_id", user.organization_id)
        .execute()
    )
    collections = [_project_to_collection(p, request) for p in (result.data or [])]
    return {
        "collections": collections,
        "links": [
            {"rel": "self", "href": _self_url(request, "/collections"), "type": "application/json"},
            {"rel": "root", "href": _self_url(request), "type": "application/json"},
        ],
    }


@router.get("/collections/{collection_id}", summary="Get a STAC Collection")
async def get_collection(
    collection_id: str,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Return a single STAC Collection by project ID."""
    result = (
        supabase.table("projects")
        .select("id, name, description, created_at")
        .eq("id", collection_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    return _project_to_collection(result.data, request)


@router.get("/collections/{collection_id}/items", summary="List items in a collection")
async def list_collection_items(
    collection_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Return all STAC Items (datasets) belonging to a project/collection."""
    # Verify the collection belongs to the user's org
    proj = (
        supabase.table("projects")
        .select("id")
        .eq("id", collection_id)
        .eq("organization_id", user.organization_id)
        .maybe_single()
        .execute()
    )
    if not proj.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")

    result = (
        supabase.table("datasets")
        .select(
            "id, name, description, project_id, created_at, capture_date, "
            "point_count, crs_epsg, processing_status, copc_url, raw_s3_key, "
            "ifc_url, road_assets_url, dtm_url, bbox_geom"
        )
        .eq("project_id", collection_id)
        .range(offset, offset + limit - 1)
        .execute()
    )

    items = [_dataset_to_item(ds, request) for ds in (result.data or [])]
    return {
        "type": "FeatureCollection",
        "features": items,
        "numberMatched": len(items),
        "numberReturned": len(items),
        "links": [
            {"rel": "self", "href": _self_url(request, f"/collections/{collection_id}/items"), "type": "application/geo+json"},
            {"rel": "root", "href": _self_url(request), "type": "application/json"},
            {"rel": "collection", "href": _self_url(request, f"/collections/{collection_id}"), "type": "application/json"},
        ],
    }


# ── STAC Search ───────────────────────────────────────────────────────────────

class STACSearchBody(BaseModel):
    bbox: Optional[list[float]] = None          # [west, south, east, north]
    datetime: Optional[str] = None              # RFC 3339 or interval "start/end"
    collections: Optional[list[str]] = None     # project IDs to filter
    limit: int = 100
    offset: int = 0


async def _execute_search(
    request: Request,
    body: STACSearchBody,
    user: AuthenticatedUser,
    supabase: Client,
) -> dict:
    """Shared implementation for GET and POST /stac/search."""
    query = supabase.table("datasets").select(
        "id, name, description, project_id, created_at, capture_date, "
        "point_count, crs_epsg, processing_status, copc_url, raw_s3_key, "
        "ifc_url, road_assets_url, dtm_url, bbox_geom"
    )

    # Filter to datasets the user can access via their org's projects
    # We join through projects — Supabase RLS handles this, but we also
    # filter explicitly for clarity.
    if body.collections:
        # Verify each collection belongs to the user's org
        proj_result = (
            supabase.table("projects")
            .select("id")
            .eq("organization_id", user.organization_id)
            .in_("id", body.collections)
            .execute()
        )
        accessible_ids = [p["id"] for p in (proj_result.data or [])]
        if not accessible_ids:
            return {"type": "FeatureCollection", "features": [], "numberMatched": 0, "numberReturned": 0, "links": []}
        query = query.in_("project_id", accessible_ids)
    else:
        # Restrict to datasets in the user's org's projects
        proj_result = (
            supabase.table("projects")
            .select("id")
            .eq("organization_id", user.organization_id)
            .execute()
        )
        project_ids = [p["id"] for p in (proj_result.data or [])]
        if not project_ids:
            return {"type": "FeatureCollection", "features": [], "numberMatched": 0, "numberReturned": 0, "links": []}
        query = query.in_("project_id", project_ids)

    # Datetime filter
    if body.datetime:
        if "/" in body.datetime:
            parts = body.datetime.split("/", 1)
            start, end = parts[0], parts[1]
            if start and start != "..":
                query = query.gte("capture_date", start)
            if end and end != "..":
                query = query.lte("capture_date", end)
        else:
            query = query.eq("capture_date", body.datetime)

    # Spatial bbox filter — use PostGIS ST_Intersects via RPC if bbox provided
    # For simplicity without a custom RPC function, we apply a bounding box
    # filter on the stored bbox_geom using Supabase's PostGIS support.
    # Full spatial indexing requires the migration in PRD-02 section 4.3.
    if body.bbox and len(body.bbox) == 4:
        west, south, east, north = body.bbox
        # Use PostGIS envelope intersection via a raw filter
        # This relies on the bbox_geom column being a PostGIS geometry type
        query = query.filter(
            "bbox_geom",
            "ov",  # overlaps operator — works with PostGIS box types
            f"[({west},{south}),({east},{north})]",
        )

    result = query.range(body.offset, body.offset + body.limit - 1).execute()
    items = [_dataset_to_item(ds, request) for ds in (result.data or [])]

    return {
        "type": "FeatureCollection",
        "features": items,
        "numberMatched": len(items),
        "numberReturned": len(items),
        "links": [
            {"rel": "self", "href": _self_url(request, "/search"), "type": "application/geo+json"},
            {"rel": "root", "href": _self_url(request), "type": "application/json"},
        ],
    }


@router.get("/search", summary="Search STAC Items (GET)")
async def search_items_get(
    request: Request,
    bbox: Optional[str] = Query(
        default=None,
        description="Bounding box as west,south,east,north (e.g. 150.0,-34.0,152.0,-33.0)",
    ),
    datetime: Optional[str] = Query(default=None, description="RFC 3339 datetime or interval"),
    collections: Optional[str] = Query(default=None, description="Comma-separated project IDs"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Search STAC Items using query parameters (GET method)."""
    parsed_bbox: Optional[list[float]] = None
    if bbox:
        try:
            parsed_bbox = [float(v) for v in bbox.split(",")]
            if len(parsed_bbox) != 4:
                raise ValueError
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="bbox must be four comma-separated floats: west,south,east,north",
            )

    parsed_collections: Optional[list[str]] = None
    if collections:
        parsed_collections = [c.strip() for c in collections.split(",") if c.strip()]

    body = STACSearchBody(
        bbox=parsed_bbox,
        datetime=datetime,
        collections=parsed_collections,
        limit=limit,
        offset=offset,
    )
    return await _execute_search(request, body, user, supabase)


@router.post("/search", summary="Search STAC Items (POST)")
async def search_items_post(
    request: Request,
    body: STACSearchBody,
    user: AuthenticatedUser = Depends(get_current_user),
    supabase: Client = Depends(get_supabase),
):
    """Search STAC Items using a JSON request body (POST method)."""
    return await _execute_search(request, body, user, supabase)
