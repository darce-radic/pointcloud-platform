# PointCloud Platform — AI Developer Context

Welcome to the PointCloud Platform codebase. This document provides the context, architectural decisions, and strict rules you need to follow when writing code for this project.

**Goal:** Build a multi-tenant, cloud-native 3D point cloud processing and visualization platform.

## 🏗️ Architecture & Stack

- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui.
- **3D Viewer:** CesiumJS (global context) + Potree (COPC streaming).
- **Backend API:** FastAPI (Python 3.11), Pydantic v2.
- **Database / Auth / Realtime:** Supabase (PostgreSQL + PostGIS + pgvector).
- **Processing:** Kubernetes, KEDA, Argo Workflows.
- **AI Agent:** LangGraph (Python), OpenAI GPT-4o.

## 📚 Documentation First

Before writing any code, you MUST read the relevant documentation in the `docs/` folder:
- `docs/architecture/System_Design.md` — The source of truth for system architecture.
- `docs/prd/Platform_PRD.md` — User stories and acceptance criteria.
- `docs/api/OpenAPI_Specification.md` — Data contracts and endpoint designs.

## 🚦 Strict Rules for AI Coding

1. **Never mock the database.** We use Supabase. Use the `supabase-js` client in the frontend and the official Python `supabase` client in the backend.
2. **Never build a tile server.** We use the **COPC** (Cloud Optimized Point Cloud) format. Point clouds stream directly from S3 to the browser via HTTP Range requests.
3. **Always use dark mode.** The UI is Apple-inspired monochrome dark mode. Do not use bright blues, purples, or greens. Rely on the variables in `globals.css`.
4. **Enforce Multi-Tenancy.** Every database table has an `organization_id`. Every API request must validate the user's organization. Row-Level Security (RLS) is enabled on all tables.
5. **Types are the source of truth.** If you change a database schema, you MUST update `frontend/src/types/index.ts` and the Pydantic models in `api/models/`.

## 🛠️ Common Tasks

### Adding a new API Endpoint
1. Define the Pydantic request/response models in `api/routers/`.
2. Ensure the endpoint checks `organization_id`.
3. Add the endpoint to `api/main.py`.

### Adding a new AI Tool
1. Open `api/agent/tools.py`.
2. Define a strict Pydantic input schema.
3. Write the tool function and decorate it with `@tool(args_schema=...)`.
4. Add the function to the `TOOLS` list at the bottom of the file.

### Adding a new Processing Worker
1. Create a new folder in `workers/`.
2. Write the Python `entrypoint.py` that accepts `dataset_id`, `s3_input_key`, `s3_output_key`, and `job_id` as arguments.
3. Ensure the worker updates the `processing_jobs` table status via Supabase.
4. Write the `Dockerfile`.

## 🚀 "Vibe Coding" Starter Prompt

If you are starting a new session, use this prompt to orient yourself:

> "I want to work on the PointCloud Platform. Please read `CLAUDE.md` and `docs/architecture/System_Design.md` to understand the architecture. I want to start by building the [insert feature here, e.g., 'direct S3 upload flow in the frontend']. Check the PRD for the requirements, and let's write the code."
