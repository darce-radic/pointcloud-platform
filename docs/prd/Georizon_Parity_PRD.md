# Product Requirements Document: Georizon Feature Parity

## 1. Overview

This document outlines the product requirements for bringing the PointCloud Platform into feature parity with the Georizon automated processing platform. The primary audience for this document is the engineering team and autonomous coding agents (e.g., Claude Code). 

The goal is to expand the platform from a strict LiDAR viewer into a comprehensive, multi-sensor geodata processing platform featuring a synchronized multi-dimensional viewer (2D Map, 3D Point Cloud, 360° Panoramic Imagery) and a robust data harmonization pipeline.

## 2. Core Modules

The required features are grouped into three distinct modules:
1. **Module 1: Tri-Panel Synchronized Viewer** (Frontend)
2. **Module 2: 360° Panoramic Imagery Integration** (Backend & Frontend)
3. **Module 3: Automated Harmonization Pipeline** (Workers & API)

---

## 3. Module 1: Tri-Panel Synchronized Viewer

### 3.1. Description
The frontend viewer must be upgraded from a single-canvas CesiumJS implementation to a synchronized three-panel layout. This layout will simultaneously display a 2D top-down map, a 3D point cloud, and a 360° panoramic image. Vector assets (e.g., road signs, light poles) must be synchronized and visible across all three views.

### 3.2. User Stories
- As an inspector, I want to see the 2D map, 3D point cloud, and 360° street view side-by-side so that I can cross-reference asset locations.
- As an inspector, I want to click an asset marker in the 2D map and have the 360° panoramic view instantly jump to the nearest image capturing that asset.
- As an inspector, I want to see the survey vehicle's trajectory path overlaid on the 2D map.
- As a data manager, I want to click on a detected road asset in the panoramic view to open its property table and edit its attributes.

### 3.3. Acceptance Criteria
- [ ] The UI supports a three-panel split layout (resizable).
- [ ] A unified state management system (e.g., Zustand or React Context) maintains the current camera position, selected asset, and visible layers across all panels.
- [ ] The 2D Map panel renders a GeoJSON trajectory line representing the survey path.
- [ ] The 2D Map panel displays a directional cone/triangle indicating the current viewing angle of the 360° panoramic viewer.
- [ ] Asset markers (GeoJSON features) render simultaneously in Leaflet (2D), CesiumJS (3D), and the Panoramic viewer (2D overlay).

### 3.4. Technical Specifications

#### State Schema (Frontend)
```typescript
interface ViewerState {
  currentLocation: { lat: number; lon: number; alt: number };
  currentHeading: number; // 0-360 degrees
  selectedAssetId: string | null;
  visibleLayers: string[];
  trajectoryId: string | null;
}
```

---

## 4. Module 2: 360° Panoramic Imagery Integration

### 4.1. Description
The platform must support the ingestion, storage, and streaming of 360° panoramic imagery captured during mobile mapping surveys. This requires linking image frames to specific geographic coordinates and timestamps along the survey trajectory.

### 4.2. User Stories
- As a surveyor, I want to upload a ZIP file containing 360° images and a CSV trajectory file so that the platform can map the images to geographic locations.
- As an inspector, I want to pan and zoom smoothly within a 360° image sphere.
- As an inspector, I want to adjust the brightness and contrast of the panoramic image to see details in shadows.

### 4.3. Acceptance Criteria
- [ ] The API accepts uploads of image archives linked to a dataset.
- [ ] A new database table `panoramic_images` stores the URL, latitude, longitude, altitude, heading, and timestamp for each image frame.
- [ ] The frontend integrates a WebGL-based panoramic viewer (e.g., Marzipano, Pannellum, or Photo Sphere Viewer).
- [ ] The panoramic viewer includes UI controls for brightness, contrast, and full-screen mode.

### 4.4. Technical Specifications

#### Database Schema Updates
```sql
CREATE TABLE panoramic_images (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dataset_id UUID REFERENCES datasets(id) ON DELETE CASCADE,
    organization_id UUID REFERENCES organizations(id),
    image_url TEXT NOT NULL,
    geom GEOMETRY(Point, 4326) NOT NULL, -- Lat/Lon
    altitude FLOAT,
    heading FLOAT, -- Yaw
    pitch FLOAT,
    roll FLOAT,
    captured_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_panoramic_images_geom ON panoramic_images USING GIST(geom);
```

#### API Endpoints
**`GET /api/v1/datasets/{dataset_id}/images/nearest`**
- **Query Params:** `lat` (float), `lon` (float), `radius` (float, default=50m)
- **Response:**
  ```json
  {
    "id": "uuid",
    "image_url": "https://s3.../image.jpg",
    "distance_meters": 4.2,
    "heading": 185.4
  }
  ```

---

## 5. Module 3: Automated Harmonization Pipeline

### 5.1. Description
A new pre-processing worker must be introduced before the tiling stage. This worker will handle Coordinate Reference System (CRS) normalization, noise reduction, and data anonymization (GDPR compliance).

### 5.2. User Stories
- As a data manager, I want the platform to automatically detect and convert local coordinate systems to a standard web format so that I don't have to pre-process files locally.
- As an enterprise user, I want the platform to automatically detect and blur faces and license plates in both the panoramic imagery and the point cloud to comply with privacy regulations.
- As an end-user, I want the point cloud to be automatically filtered for noise (floating points) so that the 3D viewer performs smoothly.

### 5.3. Acceptance Criteria
- [ ] A new `harmonization-worker` is created in the `workers/` directory.
- [ ] The worker executes a PDAL pipeline to apply `filters.outlier` and `filters.smrf` for noise reduction.
- [ ] The worker executes a computer vision model (e.g., YOLOv8) to detect vehicles and pedestrians, applying a blur filter to corresponding image regions and removing corresponding points from the LAS/LAZ file.
- [ ] The API routing logic in `datasets.py` is updated to trigger the `harmonization` job before the `tiling` job.

### 5.4. Technical Specifications

#### Job Pipeline Flow
1. Upload -> `status = uploaded`
2. Trigger Harmonization -> `job_type = harmonization`
3. Harmonization Complete -> Trigger Tiling -> `job_type = tiling`
4. Tiling Complete -> `status = ready`

#### PDAL Pipeline Specification (Harmonization Worker)
```json
[
    {
        "type": "readers.las",
        "filename": "input.laz"
    },
    {
        "type": "filters.outlier",
        "method": "statistical",
        "mean_k": 8,
        "multiplier": 3.0
    },
    {
        "type": "filters.voxelcentroidnearestneighbor",
        "cell": 0.05
    },
    {
        "type": "writers.las",
        "filename": "harmonized.laz"
    }
]
```

## 6. Security & DAO Considerations (Casitka Architecture)

In alignment with the broader Casitka Digital Twin architecture:
- All new API endpoints must enforce strict multi-tenancy via the `organization_id` field and Supabase Row-Level Security (RLS) policies.
- Processing jobs (Harmonization, Tiling, Analytics) should emit cryptographic proofs of execution to a decentralized ledger (future phase) to support a decentralized AI compute economy.
- Data anonymization (blurring) is a strict requirement for enterprise adoption and must occur before any data is made available to external AI agents or third-party integrations.
