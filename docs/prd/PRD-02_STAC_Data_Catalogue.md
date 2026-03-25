# PRD-02: STAC Data Catalogue & Discovery API

**Module:** Data Discovery
**Status:** Draft
**Target Audience:** Claude Code

## 1. Overview
As the platform scales to host hundreds of point cloud surveys, users need a standardized way to search and discover data spatially and temporally. This module implements the SpatioTemporal Asset Catalog (STAC) specification on top of the existing Supabase database, allowing the platform's datasets to be queried by standard open-source geospatial tools (like QGIS or STAC Browser).

## 2. User Stories
- As a data scientist, I want to query the platform's API using standard STAC tools (e.g., `pystac-client`) to find all point clouds in Sydney captured in 2024.
- As a user, I want a visual map-based catalogue interface where I can draw a bounding box and see all available surveys within that area.
- As an administrator, I want our platform to be interoperable with the broader open geospatial ecosystem rather than being a closed silo.

## 3. Architecture & Standards
- **Standard:** STAC (SpatioTemporal Asset Catalog) API Specification v1.0.0.
- **Implementation:** A new FastAPI router (`api/routers/stac.py`) acting as a translation layer over the existing Supabase `datasets` and `projects` tables.
- **Frontend UI:** Integration of the open-source `stac-browser` (Radiant Earth) into the platform's frontend dashboard.

## 4. Technical Specifications

### 4.1. STAC Mapping Strategy
The existing database schema maps to STAC concepts as follows:
- **STAC Catalog:** The root endpoint (`/stac`).
- **STAC Collection:** A `project` in the `projects` table.
- **STAC Item:** A `dataset` in the `datasets` table.
- **STAC Assets:** The files associated with a dataset (e.g., `copc_url`, `raw_s3_key`, `ifc_url`, `road_assets_url`).

### 4.2. API Endpoints (`api/routers/stac.py`)
Create a new router implementing the core STAC API endpoints.

**`GET /stac` (Root Catalog)**
- **Returns:** A STAC Catalog JSON object listing all available Collections (projects) the user has access to.

**`GET /stac/collections`**
- **Returns:** An array of STAC Collection objects representing the user's projects.

**`GET /stac/collections/{collection_id}`**
- **Returns:** A single STAC Collection object.

**`GET /stac/collections/{collection_id}/items`**
- **Returns:** A GeoJSON FeatureCollection of STAC Items (datasets) belonging to the project.
- **Item Geometry:** Derived from `datasets.bbox_geom` (PostGIS `ST_AsGeoJSON`).
- **Item Properties:** Includes `datetime` (from `capture_date` or `created_at`), `point_count`, `crs_epsg`.
- **Item Assets:** A dictionary mapping asset keys (`copc`, `raw`, `ifc`) to their respective R2 URLs.

**`GET /stac/search` (Item Search)**
- **Query Parameters:** `bbox` (e.g., `150.0,-34.0,152.0,-33.0`), `datetime`, `collections`.
- **Action:** Translates the `bbox` into a PostGIS `ST_Intersects` query against the `datasets` table.
- **Returns:** A GeoJSON FeatureCollection of matching STAC Items.

### 4.3. Database Requirements
Ensure the `datasets` table has a spatial index on the bounding box column to support fast STAC searches:
```sql
CREATE INDEX IF NOT EXISTS datasets_bbox_geom_idx ON public.datasets USING GIST (bbox_geom);
```

### 4.4. Frontend Integration
- Embed the Radiant Earth `stac-browser` component (or a simplified custom equivalent) in a new `/catalogue` route in the Next.js frontend.
- Configure the browser to point to the new `/api/v1/stac` endpoint.

## 5. Acceptance Criteria
- [ ] The `/stac` root endpoint returns a valid STAC Catalog JSON.
- [ ] A `GET /stac/search?bbox=...` request correctly filters datasets using PostGIS spatial queries and returns valid STAC Item GeoJSON.
- [ ] The returned STAC Items include the `copc_url` as a valid STAC Asset with the `type` set to `application/vnd.las`.
- [ ] The STAC API passes validation using the official `stac-validator` tool.
- [ ] The frontend Catalogue page displays a map with bounding boxes for all available datasets.
