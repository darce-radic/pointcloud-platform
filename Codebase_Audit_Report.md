# PointCloud Platform Codebase Audit Report

This report provides a comprehensive audit of the `pointcloud-platform` repository. It categorises every component into one of three states: **Production-Ready** (real code that executes), **Scaffolded/Partial** (architecturally correct but missing wiring), or **Mock/Placeholder** (demo code that fakes execution).

## 1. Database & Infrastructure Layer

The database and infrastructure layers are the most complete parts of the current codebase.

| Component | File Path | Status | Notes |
| :--- | :--- | :--- | :--- |
| **Database Schema** | `supabase/migrations/20260322000001_initial_schema.sql` | **Production-Ready** | Complete PostgreSQL schema with all core tables, relationships, and strict Row-Level Security (RLS) policies for multi-tenancy. |
| **Workflow Tools Schema** | `supabase/migrations/20260322000002_workflow_tools.sql` | **Production-Ready** | Complete schema for the viewer tools registry, including `pgvector` embeddings and semantic search functions. *Note: Seed data contains fake webhook URLs.* |
| **S3 Terraform** | `infra/terraform/modules/s3/main.tf` | **Production-Ready** | Correctly configures S3 and CloudFront with the necessary CORS and `Range` header forwarding required for COPC streaming. |
| **KEDA Autoscaler** | `infra/k8s/keda/sqs-scaledobject.yaml` | **Scaffolded** | Architecturally correct Kubernetes manifest, but uses a placeholder `ACCOUNT_ID` for the SQS queue URL. |
| **Argo Workflow** | `infra/k8s/argo-workflows/tiling-workflow.yaml` | **Scaffolded** | Correctly defines the DAG for the tiling job, but points to a placeholder ECR image URI (`your-ecr-account...`). |

## 2. API Backend (FastAPI)

The API layer is currently a structural skeleton. The routing and data models exist, but the actual business logic is mocked or marked with TODOs.

| Component | File Path | Status | Notes |
| :--- | :--- | :--- | :--- |
| **API Entry Point** | `api/main.py` | **Scaffolded** | FastAPI app is initialized with CORS, but all router inclusions are commented out. |
| **Datasets Router** | `api/routers/datasets.py` | **Scaffolded** | Generates real AWS S3 presigned URLs using `boto3`, but Supabase database inserts and Argo workflow triggers are just TODO comments. |
| **Conversations Router** | `api/routers/conversations.py` | **Mock** | Implements the Server-Sent Events (SSE) streaming structure, but streams a hardcoded placeholder string instead of calling the LangGraph agent. |
| **Supabase Edge Function** | `supabase/functions/process-upload/index.ts` | **Scaffolded** | Correctly inserts a `processing_jobs` row into Supabase, but the code to actually trigger the Argo workflow is a TODO. |

## 3. Agentic AI Layer (LangGraph)

The AI agent is fully architected but relies on mock data for its external integrations.

| Component | File Path | Status | Notes |
| :--- | :--- | :--- | :--- |
| **Agent Graph** | `api/agent/graph.py` | **Partially Real** | The LLM routing, planning, JSON generation, and validation logic is real and uses `gpt-4.1-mini`. However, `node_selector` uses a hardcoded `MOCK_NODE_LIBRARY` dictionary instead of querying pgvector, and `deployer` generates a fake UUID instead of calling the n8n API. |
| **Agent Tools** | `api/agent/tools.py` | **Mock** | Pydantic schemas are correct, but the tool functions (`search_geospatial_nodes`, `generate_and_deploy_workflow`) return fake success strings without executing real side effects. |

## 4. Frontend Application (React/Vite)

The frontend contains real UI components and database subscriptions, but depends on the mocked backend endpoints.

| Component | File Path | Status | Notes |
| :--- | :--- | :--- | :--- |
| **Job Status Hook** | `frontend/src/hooks/useJobStatus.ts` | **Production-Ready** | Fully functional real-time subscription using Supabase `postgres_changes`. Will work immediately once the database receives live updates. |
| **Type Definitions** | `frontend/src/types/index.ts` | **Production-Ready** | Comprehensive TypeScript interfaces that perfectly mirror the Supabase database schema. |
| **Viewer Toolbar** | `frontend/src/components/viewer/ViewerToolbar.tsx` | **Partially Real** | Correctly fetches tools from Supabase and handles UI state. However, it relies on an unwritten `useViewerState` hook and attempts to POST to the fake webhook URLs seeded in the database. |
| **AI Chat Panel** | `frontend/src/components/ai-chat/AiChatPanel.tsx` | **Partially Real** | Real UI component that correctly parses SSE streams, but it calls the mocked `/conversations/{id}/messages` endpoint. |
| **Showcase Website** | `showcase/index.html` | **Mock (Marketing)** | A polished, production-ready static marketing webpage. All "interactive" elements (chat, workflow generation, viewer) are hardcoded HTML/JS simulations for demonstration purposes. |

## 5. Processing Workers

The worker layer contains the most complete execution code in the repository.

| Component | File Path | Status | Notes |
| :--- | :--- | :--- | :--- |
| **Tiling Worker** | `workers/tiling/src/entrypoint.py` | **Production-Ready** | A fully functional Python script that downloads from S3, executes a real PDAL pipeline to generate a COPC file, uploads the result, and updates the Supabase job status. |
| **Tiling Dockerfile** | `workers/tiling/Dockerfile` | **Production-Ready** | Correctly packages the PDAL base image with Python dependencies. |
| **BIM / Road Asset Dockerfiles** | `workers/bim-extraction/Dockerfile`, `workers/road-assets/Dockerfile` | **Scaffolded** | Complex dependency chains (PyTorch, Open3D, Cloud2BIM) are correctly specified, but the actual `src/entrypoint.py` implementation files for these workers do not exist in the repository yet. |

## Remediation Roadmap

To move this codebase from a scaffold to a fully executable platform, the following wiring tasks must be completed in order:

1. **Uncomment API Routers:** Update `api/main.py` to include the datasets and conversations routers.
2. **Wire Datasets to Database:** Replace the TODOs in `api/routers/datasets.py` with actual Supabase `insert()` calls.
3. **Connect Chat to Agent:** Update `api/routers/conversations.py` to call `build_workflow_agent().stream()` instead of yielding the placeholder string.
4. **Replace Mock Node Library:** Update `api/agent/graph.py` to query the `workflow_node_schemas` table using the `search_nodes_by_similarity` RPC function.
5. **Implement n8n Deployment:** Update `api/agent/tools.py` to actually `POST` the generated JSON to an n8n instance.
6. **Write Missing Worker Scripts:** Implement the Python entrypoints for the BIM and Road Asset workers.
