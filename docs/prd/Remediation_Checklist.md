# PointCloud Platform: Remediation Checklist

This document provides a granular, file-by-file checklist of all required fixes identified during the codebase audit. It is designed to be executed systematically by Claude Code to move the platform from a scaffold to a functional state.

---

## 1. Database Schema Mismatches

The API layer and the Supabase migrations are fundamentally out of sync. The API code references tables and columns that do not exist in the migrations, or uses different naming conventions.

### 1.1. Missing Tables
The API routers query tables that are not defined in `20260322000001_initial_schema.sql` or `001_processing_jobs.sql`.
- [ ] **Action:** Create a new migration file (e.g., `003_missing_tables.sql`) to define the following tables:
  - `profiles` (referenced in `billing.py` and `001_processing_jobs.sql` RLS policies). Needs `id` (UUID references auth.users), `organization_id`, `stripe_customer_id`, `subscription_plan`, `subscription_status`, `storage_limit_bytes`.
  - `n8n_workflows` (referenced in `api/agent/tools.py`). Needs `id`, `name`, `workflow_json`, `status`, `created_by_agent`, `tags`.

### 1.2. Table Name Mismatches
- [ ] **Action:** In `api/routers/conversations.py`, rename all `.table("ai_conversations")` calls to `.table("conversations")` to match the migration.
- [ ] **Action:** In `api/routers/conversations.py`, rename all `.table("ai_messages")` calls to `.table("messages")` to match the migration.
- [ ] **Action:** In `001_processing_jobs.sql`, drop the `jobs` table from `20260322000001_initial_schema.sql` to avoid confusion, as the API exclusively uses `processing_jobs`.

### 1.3. Missing Columns in `datasets`
The `api/routers/datasets.py` and worker entrypoints write to columns that do not exist in the `datasets` table migration.
- [ ] **Action:** Create a migration to add the following columns to `datasets`:
  - `road_assets_url` (TEXT)
  - `road_asset_stats` (JSONB)
  - `ifc_url` (TEXT)
  - `dxf_url` (TEXT)
  - `segments_url` (TEXT)
  - `bim_stats` (JSONB)
  - `copc_url` (TEXT) — Note: migration 001 adds this, but ensure it exists.

---

## 2. API & Router Fixes

### 2.1. Missing Workflow Execution Endpoint
The frontend `ViewerClient.tsx` calls `POST /api/v1/workflow-tools/{toolId}/run`, but this endpoint is missing.
- [ ] **Action:** Create `api/routers/workflow_tools.py`.
- [ ] **Action:** Implement `POST /workflow-tools/{toolId}/run`. It must look up the tool by ID, get the `webhook_url`, forward the `inputs` payload to the n8n webhook via `httpx`, and return a mock or real `job_id`.
- [ ] **Action:** Register `workflow_tools.router` in `api/main.py`.

### 2.2. Chat Streaming Endpoint Mismatch
The frontend calls `/api/v1/conversations/stream`, but the router defines it as `/api/v1/agent/chat` (stateless) and `/api/v1/conversations/{conv_id}/messages` (stateful).
- [ ] **Action:** In `frontend/components/ai-chat/AiChatPanel.tsx` (line 69), change the fetch URL to `${apiUrl}/api/v1/conversations/${conversationId || 'new'}/messages` (or similar logic depending on how the frontend handles new conversations).
- [ ] **Action:** Ensure the `conversations.py` router correctly handles the `POST /conversations/{conv_id}/messages` route with SSE streaming.

### 2.3. Hardcoded Webhook URLs
- [ ] **Action:** In `api/routers/billing.py` (lines 21-22) and `api/routers/organizations.py` (line 16), remove the hardcoded `https://n8n-production-74b2f.up.railway.app` URLs.
- [ ] **Action:** Add `N8N_PAYMENT_FAILED_WEBHOOK` and `N8N_NEW_USER_WEBHOOK` to `api/config.py` as environment variables, and reference `settings.N8N_PAYMENT_FAILED_WEBHOOK` in the routers.

---

## 3. Agent & AI Layer Fixes

### 3.1. Populate Node Library
The LangGraph agent's `node_selector` function falls back to a generic node because the `workflow_node_schemas` table is empty.
- [ ] **Action:** Create a seed script or migration to populate `workflow_node_schemas` with real n8n node JSON definitions (e.g., `n8n-nodes-geospatial.pdalPipelineBuilder`, `n8n-nodes-geospatial.cloud2bim`).

---

## 4. Worker Layer Fixes

### 4.1. BIM Extraction Stub Replacement
The `workers/bim-extraction/src/entrypoint.py` file is currently a mock. It creates dummy IFC and DXF files without running real processing.
- [ ] **Action:** Implement the actual `_heuristic_segmentation` logic using `pdal` to detect planes, rather than returning hardcoded bounding boxes.
- [ ] **Action:** Implement the actual `generate_ifc` logic using `ifcopenshell` to build walls and slabs from the detected planes.

### 4.2. Road Assets Fallback Logic
The `workers/road-assets/src/entrypoint.py` file has a `detect_traffic_signs` function that falls back to a "geometric fallback" if OpenPCDet is not available.
- [ ] **Action:** Implement the geometric fallback logic using PDAL intensity/reflectance filtering to detect highly reflective vertical signs, rather than returning a hardcoded dummy sign.

---

## 5. Frontend Fixes

### 5.1. Hardcoded API URLs
Multiple components fall back to `http://localhost:8000` if `NEXT_PUBLIC_API_URL` is missing.
- [ ] **Action:** Ensure `NEXT_PUBLIC_API_URL` is defined in `frontend/.env.local`. The fallback logic is acceptable for local dev, but ensure production deployments have this variable set.

### 5.2. CesiumViewer Fallback Coordinates
If a dataset has no `copc_url`, the viewer flies to Sydney, Australia (`151.2093, -33.8688`).
- [ ] **Action:** In `frontend/components/viewer/CesiumViewer.tsx` (line 139), update the fallback logic to either show a "Processing" overlay instead of loading the globe, or extract the centroid from the dataset's `bounding_box` property if available.

### 5.3. Missing Tri-Panel Implementation (Georizon Parity)
As detailed in the `Georizon_Parity_PRD.md`, the platform lacks the 360° panoramic viewer and cross-view synchronization.
- [ ] **Action:** Update `ViewerClient.tsx` to include a third panel for 360° imagery (e.g., using Pannellum or Marzipano).
- [ ] **Action:** Update `MapPanel.tsx` to accept a `trajectoryGeoJSON` prop and render it as a polyline.
- [ ] **Action:** Implement a Zustand store to synchronize the `selectedAssetId` and `cameraPosition` across all three panels.
