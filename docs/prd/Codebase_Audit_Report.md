# Codebase Audit Report: PointCloud Platform

## 1. Executive Summary

A comprehensive audit of the `pointcloud-platform` repository was conducted to identify gaps between the current codebase state and the requirements outlined in the Platform PRD. The audit focused on locating mock implementations, hardcoded values, missing API wiring, database schema mismatches, and unimplemented modules.

The codebase is currently in a "scaffolded" state. While the frontend UI is well-developed and visually complete, the backend API, AI agent, and worker layers contain significant gaps, mock data, and incomplete integrations. 

## 2. Critical Gaps & Mocks Identified

### 2.1. API & Router Layer
- **Missing Endpoints:** The frontend `ViewerClient` attempts to call `POST /api/v1/workflow-tools/{toolId}/run` (line 507), but this endpoint does not exist anywhere in the API routers.
- **Agent Chat Streaming:** The `AiChatPanel` calls `POST /api/v1/conversations/stream` (line 69), but the `conversations.py` router only defines `POST /api/v1/agent/chat` and `POST /api/v1/conversations/{conv_id}/messages`. The endpoint paths do not match.
- **Hardcoded URLs:** The billing router contains hardcoded Railway n8n webhook URLs: `https://n8n-production-74b2f.up.railway.app/webhook/payment-failed` and `new-user-onboarding`.
- **Database Mismatches:** The API code references tables that do not exist in the Supabase migrations, specifically `ai_conversations`, `ai_messages`, `profiles`, and `n8n_workflows`. The migrations define `conversations` and `messages` without the `ai_` prefix.

### 2.2. Agent & AI Layer
- **Mock Node Fallback:** The LangGraph agent (`api/agent/graph.py`) includes a `node_selector` function that attempts to query a pgvector database. However, if the query fails (which it will, as the `workflow_node_schemas` table is not populated), it falls back to a hardcoded `n8n-nodes-geospatial.pdalPipelineBuilder` node.
- **Unused Agent Tool:** The `publish_workflow_as_viewer_tool` tool inserts into `workflow_tools`, but the frontend `ViewerClient` expects to execute these tools via an API endpoint that does not exist.

### 2.3. Frontend Layer
- **Hardcoded API URLs:** Across the frontend (e.g., `AiChatPanel.tsx`, `DatasetActions.tsx`, `UploadDatasetButton.tsx`, `BillingClient.tsx`), the API URL falls back to `http://localhost:8000` if the environment variable is missing.
- **Hardcoded Viewer Coordinates:** If a dataset lacks a COPC URL, the `CesiumViewer.tsx` falls back to a hardcoded location in Sydney, Australia (`151.2093, -33.8688`).
- **Missing Tri-Panel Implementation:** The `ViewerClient.tsx` currently only implements the 3D Cesium viewer and the 2D Leaflet map. The 360° panoramic viewer is entirely missing.

### 2.4. Worker Layer
- **BIM Extraction Stub:** The `bim-extraction` worker entrypoint is a complete stub. It creates a dummy `output.ifc` and `output.dxf` file without actually processing the point cloud data.
- **Road Assets Implementation:** The `road-assets` worker has a more complete entrypoint, but it relies on external functions (`preprocess_and_classify`, `extract_road_surface`, etc.) that are imported but not fully implemented in the repository.

## 3. Prioritised Remediation Plan

The following table outlines the required remediation tasks in priority order, suitable for an autonomous coding agent (e.g., Claude Code) to execute.

| Priority | Component | Issue Description | Remediation Action |
| :--- | :--- | :--- | :--- |
| **P1** | Database | Schema mismatch between API and migrations. | Update `api/routers/*.py` to use correct table names (`conversations` instead of `ai_conversations`), or update migrations to match API expectations. Create the missing `profiles` and `n8n_workflows` tables. |
| **P2** | API | Missing workflow execution endpoint. | Implement `POST /api/v1/workflow-tools/{toolId}/run` in the API to trigger n8n webhooks based on the tool definition. |
| **P3** | API / Frontend | Chat streaming endpoint mismatch. | Align the `AiChatPanel.tsx` fetch call with the actual endpoint defined in `conversations.py` (`/api/v1/conversations/{conv_id}/messages`). |
| **P4** | Agent | Mock node selector fallback. | Populate the `workflow_node_schemas` table with actual n8n node definitions so the agent can select real processing steps instead of the generic fallback. |
| **P5** | Frontend | Hardcoded API URLs and fallback coordinates. | Ensure `NEXT_PUBLIC_API_URL` is correctly set in `.env.local` and remove hardcoded localhost fallbacks. Update `CesiumViewer` to handle missing COPC URLs more gracefully. |
| **P6** | Workers | BIM Extraction worker is a stub. | Implement the actual Cloud2BIM processing logic in the `bim-extraction` worker entrypoint. |
| **P7** | Frontend | Missing 360° Panoramic Viewer. | Implement the tri-panel layout as specified in the Georizon Parity PRD, adding the panoramic viewer and cross-view synchronization. |

## 4. Conclusion

To transition the PointCloud Platform from a scaffold to a functional prototype, the immediate focus must be on resolving the API-to-Database schema mismatches (P1) and wiring up the missing endpoints (P2, P3). Once the core infrastructure is stable, the AI agent's node library (P4) and the specialized processing workers (P6) can be fully implemented.
