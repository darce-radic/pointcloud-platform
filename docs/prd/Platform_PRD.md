# Product Requirements Document: PointCloud Platform

## 1. Overview

This document outlines the complete product requirements for the PointCloud Platform, a multi-tenant, cloud-native 3D geodata processing and visualization application. It serves as a core module within the broader Casitka Digital Twin architecture. The primary audience for this document is autonomous coding agents (e.g., Claude Code) and the engineering team.

The platform is designed to ingest raw LiDAR and spatial data, automate the harmonization and tiling processes, execute specialized analytics (e.g., BIM extraction, road asset detection), and present the results in a highly interactive, synchronized multi-dimensional viewer. Furthermore, it incorporates an AI agent layer capable of dynamically generating and deploying processing workflows via n8n.

## 2. Core Principles & Constraints

- **Multi-Tenancy:** Every data entity (dataset, project, job, conversation) must be scoped to an `organization_id`. Supabase Row-Level Security (RLS) is mandatory across all tables.
- **Backend Infrastructure:** Supabase PostgreSQL is the absolute source of truth. No mocking of database layers is permitted. Cloudflare R2 (S3-compatible) is used for all blob storage.
- **Streaming over Serving:** The platform uses Cloud Optimized Point Cloud (COPC) formats. Point clouds stream directly from R2 to the browser via HTTP Range requests; no traditional tile servers are used.
- **Decentralized Readiness:** In alignment with Casitka DAO principles, processing jobs should be structured to eventually emit cryptographic proofs of execution, supporting a decentralized AI compute economy.
- **Design Language:** The frontend utilizes an Apple-inspired monochrome dark mode.

---

## 3. Module 1: Data Ingestion & Harmonization Pipeline

### 3.1. Description
The platform must ingest raw spatial data (LAS/LAZ files, trajectory data, and 360° panoramic imagery), validate it, and automatically harmonize it into web-ready formats.

### 3.2. User Stories
- As a surveyor, I want to upload raw LAS/LAZ files directly from my browser to cloud storage without file size limits.
- As a data manager, I want the system to automatically normalize coordinate reference systems (CRS) to a standard web format.
- As an enterprise user, I want the system to automatically blur faces and license plates in point clouds and imagery to ensure GDPR compliance.
- As an end-user, I want raw point clouds to be automatically tiled into COPC format so they stream smoothly in the web viewer.

### 3.3. Acceptance Criteria
- [ ] The API provides a secure, short-lived presigned URL for direct client-to-S3 uploads.
- [ ] Uploading triggers an event-driven pipeline via Supabase `processing_jobs`.
- [ ] A `harmonization-worker` executes a PDAL pipeline to apply noise reduction (`filters.outlier`, `filters.smrf`) and density normalization (`filters.voxelcentroidnearestneighbor`).
- [ ] A computer vision pass (e.g., YOLOv8) detects and blurs vehicles and pedestrians in the harmonization phase.
- [ ] A `tiling-worker` converts the harmonized data into COPC format and updates the dataset record with the `copc_url`.

### 3.4. Technical Specifications

**Database Schema: Datasets**
```sql
CREATE TABLE datasets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES organizations(id),
    project_id UUID REFERENCES projects(id),
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('uploading', 'uploaded', 'processing', 'ready', 'failed')),
    format TEXT,
    raw_s3_key TEXT,
    copc_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**API Endpoints**
- `POST /api/v1/datasets/upload-url`: Generate presigned R2 upload URL.
- `GET /api/v1/datasets/{id}`: Retrieve dataset metadata and processing status.

---

## 4. Module 2: Synchronized Tri-Panel Viewer

### 4.1. Description
The visualization interface must support a synchronized three-panel layout to view geodata across multiple dimensions simultaneously: 2D map, 3D point cloud, and 360° panoramic imagery.

### 4.2. User Stories
- As an inspector, I want to view the 2D map, 3D point cloud, and 360° street view side-by-side to cross-reference asset locations.
- As an inspector, I want to click an asset marker in the 2D map and have the 360° panoramic view instantly jump to the nearest image capturing that asset.
- As a data manager, I want to see the survey vehicle's trajectory path overlaid on the 2D map.
- As an analyst, I want to measure distances and heights directly within the 3D point cloud.

### 4.3. Acceptance Criteria
- [ ] The frontend UI implements a resizable three-panel layout.
- [ ] A unified state management system (e.g., Zustand) maintains the current camera position, selected asset, and visible layers across all panels.
- [ ] The 2D Map panel (Leaflet) renders a GeoJSON trajectory line and a directional cone indicating the 360° viewer's heading.
- [ ] The 3D Point Cloud panel (CesiumJS) streams COPC data and supports RGB, Intensity, and Elevation render modes.
- [ ] Asset markers (GeoJSON features) render simultaneously in all three views. Clicking an asset in one view highlights it in the others.
- [ ] The 360° viewer (e.g., Marzipano/Pannellum) includes controls for brightness and contrast.

### 4.4. Technical Specifications

**Frontend State Schema**
```typescript
interface ViewerState {
  currentLocation: { lat: number; lon: number; alt: number };
  currentHeading: number; // 0-360 degrees
  selectedAssetId: string | null;
  visibleLayers: string[];
  trajectoryId: string | null;
}
```

**Database Schema: Panoramic Images**
```sql
CREATE TABLE panoramic_images (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dataset_id UUID REFERENCES datasets(id) ON DELETE CASCADE,
    organization_id UUID REFERENCES organizations(id),
    image_url TEXT NOT NULL,
    geom GEOMETRY(Point, 4326) NOT NULL,
    heading FLOAT,
    captured_at TIMESTAMPTZ
);
CREATE INDEX idx_panoramic_images_geom ON panoramic_images USING GIST(geom);
```

---

## 5. Module 3: Specialized Analytics Workers

### 5.1. Description
The platform must support specialized asynchronous processing workers that extract structured intelligence from raw point clouds.

### 5.2. User Stories
- As a civil engineer, I want to extract road surface markings, traffic signs, and drains from a mobile mapping dataset into a standard GeoJSON format.
- As an architect, I want to extract structural elements (walls, slabs, doors) from an indoor scan into an IFC 4 BIM model and a DXF floor plan.

### 5.3. Acceptance Criteria
- [ ] A `road-assets-worker` exists that processes LAZ files to extract road surfaces, markings, and signs, outputting a GeoJSON FeatureCollection.
- [ ] A `bim-extraction-worker` exists that processes LAZ files to identify structural planes, outputting an IFC 4 file and a layered DXF floor plan.
- [ ] Workers poll the `processing_jobs` table, update progress percentages in real-time, and write final outputs to R2.
- [ ] The API exposes endpoints to trigger these specific jobs manually.

### 5.4. Technical Specifications

**API Endpoints**
- `POST /api/v1/datasets/{id}/road-assets`: Queue road asset extraction.
- `POST /api/v1/datasets/{id}/bim-extraction`: Queue BIM extraction.

---

## 6. Module 4: Agentic AI Workflow Generator

### 6.1. Description
An integrated LangGraph-based AI agent that interacts with users via chat, understands their geospatial processing intent, and dynamically generates and deploys n8n processing workflows.

### 6.2. User Stories
- As a user, I want to chat with an AI assistant to ask questions about my point cloud data.
- As a data engineer, I want to describe a processing pipeline in natural language (e.g., "Crop this cloud, filter noise, and extract buildings"), and have the AI generate the exact workflow.
- As a platform admin, I want the AI to deploy the generated workflow to n8n and publish it as a one-click button in the 3D viewer toolbar.

### 6.3. Acceptance Criteria
- [ ] The API exposes a Server-Sent Events (SSE) endpoint for real-time chat streaming.
- [ ] The LangGraph agent routes intents between general chat and workflow generation.
- [ ] The agent queries a pgvector database of `workflow_node_schemas` to find the correct n8n nodes for the requested pipeline.
- [ ] The agent generates valid n8n JSON and uses the n8n API to deploy it.
- [ ] The agent uses a tool to insert a record into the `workflow_tools` table, making the new workflow available in the frontend viewer UI.

### 6.4. Technical Specifications

**Agent State Schema**
```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    intent: Optional[str]
    planned_steps: Optional[List[Dict]]
    node_schemas: Optional[List[Dict]]
    generated_workflow: Optional[Dict]
    deployed_workflow_id: Optional[str]
    dataset_id: Optional[str]
    organization_id: str
```

**Database Schema: Workflow Tools**
```sql
CREATE TABLE workflow_tools (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    organization_id UUID REFERENCES organizations(id),
    n8n_workflow_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    icon TEXT,
    webhook_url TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE
);
```

---

## 7. Known Gaps & Remediation Requirements

Based on the codebase audit, the following critical gaps must be addressed by the engineering team to move the platform from scaffold to production:

1. **API Router Activation:** The FastAPI entry point (`api/main.py`) currently has routers commented out. These must be activated and wired correctly.
2. **Database Wiring:** The `datasets.py` router generates S3 URLs but lacks the actual Supabase `insert()` calls to create database records.
3. **Agent Integration:** The `conversations.py` router currently streams mock data. It must be wired to execute the `build_workflow_agent().stream()` logic.
4. **Mock Node Replacement:** The LangGraph agent currently uses a hardcoded dictionary for node schemas. It must be updated to query the `workflow_node_schemas` pgvector table.
5. **Worker Implementation:** The Dockerfiles for `bim-extraction` and `road-assets` exist, but the actual Python entrypoint scripts containing the processing logic are missing and must be written.
6. **Georizon Parity:** The features outlined in Module 1 (Harmonization Worker) and Module 2 (Tri-Panel Viewer / Panoramic Images) are entirely missing and represent net-new development.
