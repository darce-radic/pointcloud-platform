# PointCloud Platform: Canonical Data Model & Schema

**Status:** Draft
**Target Audience:** Claude Code, Database Administrators

## 1. Overview

This document defines the canonical data model for the PointCloud Platform. It consolidates the existing Supabase migrations (`20260322000001_initial_schema.sql` and `001_processing_jobs.sql`) and integrates all the missing tables and columns identified during the codebase audit (e.g., `profiles`, `n8n_workflows`, `workflow_tools`, and missing `datasets` columns).

The platform uses a **multi-tenant architecture** where all core entities are isolated by an `organization_id` using PostgreSQL Row Level Security (RLS).

## 2. Entity Relationship Diagram (ERD) Summary

The data model is structured around four core domains:

1. **Identity & Billing:** `users` (auth) → `profiles` → `organizations` ← `organization_members`
2. **Data Hierarchy:** `organizations` → `projects` → `datasets`
3. **Processing & Results:** `datasets` → `processing_jobs` → `features` & `panoramic_images`
4. **AI & Automation:** `datasets` → `conversations` → `messages`, plus `n8n_workflows` and `workflow_tools`.

## 3. Complete Table Definitions

### 3.1. Identity & Billing

#### `organizations`
The root tenant entity.
- `id` (UUID, PK)
- `name` (TEXT, NOT NULL)
- `slug` (TEXT, UNIQUE, NOT NULL)
- `created_at` (TIMESTAMPTZ)
- `updated_at` (TIMESTAMPTZ)

#### `profiles` (New Table)
Extends the Supabase `auth.users` table with platform-specific billing and storage limits.
- `id` (UUID, PK, FK to `auth.users(id)`)
- `organization_id` (UUID, FK to `organizations(id)`)
- `stripe_customer_id` (TEXT)
- `subscription_plan` (TEXT, Default 'trial', Check: 'trial', 'professional', 'business', 'enterprise')
- `subscription_status` (TEXT, Default 'active')
- `storage_limit_bytes` (BIGINT, Default 10737418240 - 10GB)
- `created_at` (TIMESTAMPTZ)

#### `organization_members`
Maps users to organizations with RBAC.
- `id` (UUID, PK)
- `organization_id` (UUID, FK to `organizations(id)`)
- `user_id` (UUID, FK to `auth.users(id)`)
- `role` (TEXT, Check: 'owner', 'admin', 'editor', 'viewer')
- `invited_by` (UUID, FK to `auth.users(id)`)
- `accepted_at` (TIMESTAMPTZ)
- `created_at` (TIMESTAMPTZ)

### 3.2. Data Hierarchy

#### `projects`
Logical grouping of datasets.
- `id` (UUID, PK)
- `organization_id` (UUID, FK to `organizations(id)`)
- `name` (TEXT, NOT NULL)
- `description` (TEXT)
- `created_by` (UUID, FK to `auth.users(id)`)
- `created_at` (TIMESTAMPTZ)
- `updated_at` (TIMESTAMPTZ)

#### `datasets` (Updated)
Represents a single point cloud survey.
- `id` (UUID, PK)
- `organization_id` (UUID, FK to `organizations(id)`)
- `project_id` (UUID, FK to `projects(id)`)
- `name` (TEXT, NOT NULL)
- `description` (TEXT)
- `status` (TEXT, Default 'pending')
- `raw_s3_key` (TEXT)
- `raw_file_size_bytes` (BIGINT)
- `raw_format` (TEXT)
- `copc_s3_key` (TEXT)
- `copc_file_size_bytes` (BIGINT)
- `point_count` (BIGINT)
- `bbox_geom` (geometry(PolygonZ, 4326))
- `centroid_geom` (geometry(PointZ, 4326))
- `crs_epsg` (INTEGER)
- `capture_date` (DATE)
- `capture_type` (TEXT)
- `created_by` (UUID, FK to `auth.users(id)`)
- `created_at` (TIMESTAMPTZ)
- `updated_at` (TIMESTAMPTZ)
**New Columns Required:**
- `copc_url` (TEXT)
- `dtm_url` (TEXT)
- `road_assets_url` (TEXT)
- `road_asset_stats` (JSONB)
- `ifc_url` (TEXT)
- `dxf_url` (TEXT)
- `segments_url` (TEXT)
- `bim_stats` (JSONB)

### 3.3. Processing & Results

#### `processing_jobs`
Tracks async worker tasks.
- `id` (UUID, PK)
- `organization_id` (UUID, FK to `organizations(id)`)
- `dataset_id` (UUID, FK to `datasets(id)`)
- `job_type` (TEXT, Check: 'tiling', 'georeferencing', 'bim_extraction', 'road_assets', 'dtm_generation', 'segmentation', 'custom_workflow', 'harmonization')
- `status` (TEXT, Default 'queued')
- `progress` (INTEGER, Default 0)
- `progress_message` (TEXT)
- `worker_id` (TEXT)
- `sqs_message_id` (TEXT)
- `input_params` (JSONB)
- `output_s3_keys` (JSONB)
- `error_message` (TEXT)
- `started_at` (TIMESTAMPTZ)
- `completed_at` (TIMESTAMPTZ)
- `created_at` (TIMESTAMPTZ)
- `updated_at` (TIMESTAMPTZ)

#### `features`
Extracted individual assets (e.g., single traffic sign).
- `id` (UUID, PK)
- `organization_id` (UUID, FK to `organizations(id)`)
- `dataset_id` (UUID, FK to `datasets(id)`)
- `job_id` (UUID, FK to `processing_jobs(id)`)
- `feature_type` (TEXT)
- `feature_subtype` (TEXT)
- `label` (TEXT)
- `confidence` (FLOAT)
- `geom` (geometry(GeometryZ, 4326))
- `properties` (JSONB)
- `created_at` (TIMESTAMPTZ)

#### `panoramic_images` (New Table)
Supports the Tri-Panel Viewer.
- `id` (UUID, PK)
- `dataset_id` (UUID, FK to `datasets(id)`)
- `image_url` (TEXT, NOT NULL)
- `capture_time` (TIMESTAMPTZ)
- `geom` (geometry(PointZ, 4326), NOT NULL)
- `heading` (FLOAT)
- `pitch` (FLOAT)
- `roll` (FLOAT)

### 3.4. AI & Automation

#### `conversations`
- `id` (UUID, PK)
- `organization_id` (UUID, FK to `organizations(id)`)
- `dataset_id` (UUID, FK to `datasets(id)`)
- `title` (TEXT)
- `created_by` (UUID, FK to `auth.users(id)`)
- `created_at` (TIMESTAMPTZ)
- `updated_at` (TIMESTAMPTZ)

#### `messages`
- `id` (UUID, PK)
- `conversation_id` (UUID, FK to `conversations(id)`)
- `role` (TEXT, Check: 'user', 'assistant', 'tool')
- `content` (TEXT)
- `tool_calls` (JSONB)
- `tool_call_id` (TEXT)
- `created_at` (TIMESTAMPTZ)

#### `n8n_workflows` (New Table)
Stores AI-generated pipelines.
- `id` (UUID, PK)
- `organization_id` (UUID, FK to `organizations(id)`)
- `name` (TEXT, NOT NULL)
- `workflow_json` (JSONB, NOT NULL)
- `status` (TEXT, Default 'active')
- `created_by_agent` (BOOLEAN, Default true)
- `created_at` (TIMESTAMPTZ)

#### `workflow_tools` (New Table)
Registers a workflow as an executable button in the frontend.
- `id` (UUID, PK)
- `organization_id` (UUID, FK to `organizations(id)`)
- `name` (TEXT, NOT NULL)
- `description` (TEXT)
- `webhook_url` (TEXT, NOT NULL)
- `icon` (TEXT)
- `created_at` (TIMESTAMPTZ)

#### `workflow_node_schemas` (New Table)
Vector database for the LangGraph agent to search n8n nodes.
- `id` (UUID, PK)
- `node_type` (TEXT, UNIQUE, NOT NULL)
- `schema_json` (JSONB, NOT NULL)
- `description` (TEXT)
- `embedding` (vector(1536))

## 4. Row Level Security (RLS) Strategy

All tables must implement an RLS policy that restricts access based on `organization_id`. The canonical pattern is:

```sql
CREATE POLICY "org_isolation_<tablename>" ON public.<tablename>
FOR ALL TO authenticated
USING (organization_id = (
  SELECT organization_id FROM public.profiles WHERE id = auth.uid()
));
```
*(Note: Service roles used by the API and workers bypass RLS).*
