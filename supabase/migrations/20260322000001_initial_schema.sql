-- ============================================================
-- Migration 1: Initial Schema
-- PointCloud Platform — Multi-tenant Supabase PostgreSQL Schema
-- Run this in the Supabase SQL Editor (Dashboard > SQL Editor)
-- ============================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================
-- ORGANISATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.organizations (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name          TEXT NOT NULL,
  slug          TEXT NOT NULL UNIQUE,
  plan          TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free','professional','business','enterprise')),
  storage_used_bytes BIGINT NOT NULL DEFAULT 0,
  storage_quota_bytes BIGINT NOT NULL DEFAULT 10737418240, -- 10 GB default
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- ORGANISATION MEMBERS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.organization_members (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role            TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('owner','admin','editor','viewer')),
  invited_by      UUID REFERENCES auth.users(id),
  accepted_at     TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(organization_id, user_id)
);

-- ============================================================
-- PROJECTS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.projects (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  description     TEXT,
  created_by      UUID NOT NULL REFERENCES auth.users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- DATASETS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.datasets (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  project_id      UUID REFERENCES public.projects(id) ON DELETE SET NULL,
  name            TEXT NOT NULL,
  description     TEXT,
  status          TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','uploading','processing','ready','error')),
  -- Raw upload
  raw_s3_key      TEXT,
  raw_file_size_bytes BIGINT,
  raw_format      TEXT CHECK (raw_format IN ('las','laz','e57','ply','pcd','xyz','pts')),
  -- Processed COPC output
  copc_s3_key     TEXT,
  copc_file_size_bytes BIGINT,
  -- Spatial metadata
  point_count     BIGINT,
  bbox_geom       geometry(PolygonZ, 4326),
  centroid_geom   geometry(PointZ, 4326),
  crs_epsg        INTEGER,
  capture_date    DATE,
  -- Capture context
  capture_type    TEXT CHECK (capture_type IN ('indoor','outdoor_road','outdoor_terrain','aerial','unknown')),
  -- Timestamps
  created_by      UUID NOT NULL REFERENCES auth.users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- PROCESSING JOBS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.jobs (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  dataset_id      UUID REFERENCES public.datasets(id) ON DELETE CASCADE,
  job_type        TEXT NOT NULL
                  CHECK (job_type IN ('tiling','georeferencing','bim_extraction','road_assets','dtm_generation','segmentation','custom_workflow')),
  status          TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued','running','completed','failed','cancelled')),
  progress        INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
  progress_message TEXT,
  worker_id       TEXT,
  sqs_message_id  TEXT,
  input_params    JSONB NOT NULL DEFAULT '{}',
  output_s3_keys  JSONB NOT NULL DEFAULT '{}',
  error_message   TEXT,
  started_at      TIMESTAMPTZ,
  completed_at    TIMESTAMPTZ,
  created_by      UUID NOT NULL REFERENCES auth.users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- EXTRACTED FEATURES (road assets, BIM elements, etc.)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.features (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  dataset_id      UUID NOT NULL REFERENCES public.datasets(id) ON DELETE CASCADE,
  job_id          UUID REFERENCES public.jobs(id) ON DELETE SET NULL,
  feature_type    TEXT NOT NULL,   -- e.g. 'traffic_sign', 'road_marking', 'wall', 'door', 'drain'
  feature_subtype TEXT,            -- e.g. 'stop_sign', 'give_way', 'room_boundary'
  label           TEXT,
  confidence      FLOAT CHECK (confidence BETWEEN 0 AND 1),
  geom            geometry(GeometryZ, 4326),
  properties      JSONB NOT NULL DEFAULT '{}',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- AI CONVERSATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS public.conversations (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  dataset_id      UUID REFERENCES public.datasets(id) ON DELETE SET NULL,
  title           TEXT,
  created_by      UUID NOT NULL REFERENCES auth.users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.messages (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  conversation_id UUID NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('user','assistant','tool')),
  content         TEXT NOT NULL,
  tool_calls      JSONB,
  tool_call_id    TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_org_members_user    ON public.organization_members(user_id);
CREATE INDEX IF NOT EXISTS idx_org_members_org     ON public.organization_members(organization_id);
CREATE INDEX IF NOT EXISTS idx_projects_org        ON public.projects(organization_id);
CREATE INDEX IF NOT EXISTS idx_datasets_org        ON public.datasets(organization_id);
CREATE INDEX IF NOT EXISTS idx_datasets_project    ON public.datasets(project_id);
CREATE INDEX IF NOT EXISTS idx_datasets_status     ON public.datasets(status);
CREATE INDEX IF NOT EXISTS idx_jobs_dataset        ON public.jobs(dataset_id);
CREATE INDEX IF NOT EXISTS idx_jobs_org            ON public.jobs(organization_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status         ON public.jobs(status);
CREATE INDEX IF NOT EXISTS idx_features_dataset    ON public.features(dataset_id);
CREATE INDEX IF NOT EXISTS idx_features_type       ON public.features(feature_type);
CREATE INDEX IF NOT EXISTS idx_features_geom       ON public.features USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_datasets_bbox       ON public.datasets USING GIST(bbox_geom);
CREATE INDEX IF NOT EXISTS idx_messages_conv       ON public.messages(conversation_id);

-- ============================================================
-- UPDATED_AT TRIGGER FUNCTION
-- ============================================================
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

CREATE OR REPLACE TRIGGER trg_organizations_updated_at
  BEFORE UPDATE ON public.organizations
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE OR REPLACE TRIGGER trg_projects_updated_at
  BEFORE UPDATE ON public.projects
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE OR REPLACE TRIGGER trg_datasets_updated_at
  BEFORE UPDATE ON public.datasets
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE OR REPLACE TRIGGER trg_jobs_updated_at
  BEFORE UPDATE ON public.jobs
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE OR REPLACE TRIGGER trg_conversations_updated_at
  BEFORE UPDATE ON public.conversations
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ============================================================
-- ROW LEVEL SECURITY (RLS)
-- All tables are isolated by organization_id.
-- Users can only see data belonging to their organization.
-- ============================================================

ALTER TABLE public.organizations         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_members  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.datasets              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.jobs                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.features              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages              ENABLE ROW LEVEL SECURITY;

-- Helper function: returns the organization IDs the current user belongs to
CREATE OR REPLACE FUNCTION public.user_org_ids()
RETURNS SETOF UUID LANGUAGE sql SECURITY DEFINER STABLE AS $$
  SELECT organization_id FROM public.organization_members
  WHERE user_id = auth.uid();
$$;

-- organizations: members can see their own orgs
CREATE POLICY "org_select" ON public.organizations
  FOR SELECT USING (id IN (SELECT public.user_org_ids()));

CREATE POLICY "org_update" ON public.organizations
  FOR UPDATE USING (id IN (
    SELECT organization_id FROM public.organization_members
    WHERE user_id = auth.uid() AND role IN ('owner','admin')
  ));

-- organization_members
CREATE POLICY "members_select" ON public.organization_members
  FOR SELECT USING (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "members_insert" ON public.organization_members
  FOR INSERT WITH CHECK (organization_id IN (
    SELECT organization_id FROM public.organization_members
    WHERE user_id = auth.uid() AND role IN ('owner','admin')
  ));

-- projects
CREATE POLICY "projects_select" ON public.projects
  FOR SELECT USING (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "projects_insert" ON public.projects
  FOR INSERT WITH CHECK (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "projects_update" ON public.projects
  FOR UPDATE USING (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "projects_delete" ON public.projects
  FOR DELETE USING (organization_id IN (
    SELECT organization_id FROM public.organization_members
    WHERE user_id = auth.uid() AND role IN ('owner','admin')
  ));

-- datasets
CREATE POLICY "datasets_select" ON public.datasets
  FOR SELECT USING (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "datasets_insert" ON public.datasets
  FOR INSERT WITH CHECK (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "datasets_update" ON public.datasets
  FOR UPDATE USING (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "datasets_delete" ON public.datasets
  FOR DELETE USING (organization_id IN (
    SELECT organization_id FROM public.organization_members
    WHERE user_id = auth.uid() AND role IN ('owner','admin')
  ));

-- jobs
CREATE POLICY "jobs_select" ON public.jobs
  FOR SELECT USING (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "jobs_insert" ON public.jobs
  FOR INSERT WITH CHECK (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "jobs_update" ON public.jobs
  FOR UPDATE USING (organization_id IN (SELECT public.user_org_ids()));

-- features
CREATE POLICY "features_select" ON public.features
  FOR SELECT USING (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "features_insert" ON public.features
  FOR INSERT WITH CHECK (organization_id IN (SELECT public.user_org_ids()));

-- conversations
CREATE POLICY "conversations_select" ON public.conversations
  FOR SELECT USING (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "conversations_insert" ON public.conversations
  FOR INSERT WITH CHECK (organization_id IN (SELECT public.user_org_ids()));

-- messages (via conversation ownership)
CREATE POLICY "messages_select" ON public.messages
  FOR SELECT USING (
    conversation_id IN (
      SELECT id FROM public.conversations
      WHERE organization_id IN (SELECT public.user_org_ids())
    )
  );

CREATE POLICY "messages_insert" ON public.messages
  FOR INSERT WITH CHECK (
    conversation_id IN (
      SELECT id FROM public.conversations
      WHERE organization_id IN (SELECT public.user_org_ids())
    )
  );

-- ============================================================
-- REALTIME: enable for jobs and messages so the frontend
-- can subscribe to live updates
-- ============================================================
ALTER PUBLICATION supabase_realtime ADD TABLE public.jobs;
ALTER PUBLICATION supabase_realtime ADD TABLE public.messages;
