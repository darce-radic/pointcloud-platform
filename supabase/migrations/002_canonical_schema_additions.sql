-- ============================================================
-- Migration 002: Canonical Schema Additions
-- Purpose: Adds all missing tables and columns identified in the
--          codebase audit. This migration is additive and safe
--          to run against an existing database.
-- ============================================================

-- Required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";
CREATE EXTENSION IF NOT EXISTS "vector"; -- pgvector for AI node search

-- ============================================================
-- 1. PROFILES TABLE (missing, referenced by billing.py and RLS)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.profiles (
  id                     UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  organization_id        UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
  stripe_customer_id     TEXT,
  subscription_plan      TEXT NOT NULL DEFAULT 'trial'
                         CHECK (subscription_plan IN ('trial','starter','pro','enterprise')),
  subscription_status    TEXT NOT NULL DEFAULT 'active'
                         CHECK (subscription_status IN ('active','past_due','cancelled','trialing')),
  storage_limit_bytes    BIGINT NOT NULL DEFAULT 10737418240, -- 10 GB default trial
  storage_used_bytes     BIGINT NOT NULL DEFAULT 0,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Auto-create profile on new user signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  INSERT INTO public.profiles (id)
  VALUES (NEW.id)
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

CREATE OR REPLACE TRIGGER trg_profiles_updated_at
  BEFORE UPDATE ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "profiles_select_own" ON public.profiles
  FOR SELECT USING (id = auth.uid());

CREATE POLICY "profiles_update_own" ON public.profiles
  FOR UPDATE USING (id = auth.uid());

-- ============================================================
-- 2. MISSING COLUMNS ON datasets TABLE
-- ============================================================
ALTER TABLE public.datasets
  ADD COLUMN IF NOT EXISTS copc_url          TEXT,
  ADD COLUMN IF NOT EXISTS dtm_url           TEXT,
  ADD COLUMN IF NOT EXISTS road_assets_url   TEXT,
  ADD COLUMN IF NOT EXISTS road_asset_stats  JSONB,
  ADD COLUMN IF NOT EXISTS ifc_url           TEXT,
  ADD COLUMN IF NOT EXISTS dxf_url           TEXT,
  ADD COLUMN IF NOT EXISTS segments_url      TEXT,
  ADD COLUMN IF NOT EXISTS bim_stats         JSONB;

-- ============================================================
-- 3. RENAME jobs TABLE to processing_jobs (API uses processing_jobs)
--    The initial schema created a table named "jobs" but all API
--    routers and workers reference "processing_jobs".
-- ============================================================
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'jobs'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'processing_jobs'
  ) THEN
    ALTER TABLE public.jobs RENAME TO processing_jobs;
  END IF;
END $$;

-- Add harmonization to the job_type check if not already present
ALTER TABLE public.processing_jobs
  DROP CONSTRAINT IF EXISTS jobs_job_type_check;

ALTER TABLE public.processing_jobs
  ADD CONSTRAINT processing_jobs_job_type_check
  CHECK (job_type IN (
    'tiling','georeferencing','bim_extraction','road_assets',
    'dtm_generation','segmentation','custom_workflow','harmonization'
  ));

-- ============================================================
-- 4. PANORAMIC IMAGES TABLE (new, for Tri-Panel Viewer)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.panoramic_images (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  dataset_id    UUID NOT NULL REFERENCES public.datasets(id) ON DELETE CASCADE,
  image_url     TEXT NOT NULL,
  capture_time  TIMESTAMPTZ,
  geom          geometry(PointZ, 4326) NOT NULL,
  heading       FLOAT,  -- Camera heading in degrees (0-360)
  pitch         FLOAT,
  roll          FLOAT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pano_dataset ON public.panoramic_images(dataset_id);
CREATE INDEX IF NOT EXISTS idx_pano_geom    ON public.panoramic_images USING GIST(geom);

ALTER TABLE public.panoramic_images ENABLE ROW LEVEL SECURITY;

CREATE POLICY "pano_select" ON public.panoramic_images
  FOR SELECT USING (
    dataset_id IN (
      SELECT id FROM public.datasets
      WHERE organization_id IN (SELECT public.user_org_ids())
    )
  );

CREATE POLICY "pano_insert" ON public.panoramic_images
  FOR INSERT WITH CHECK (
    dataset_id IN (
      SELECT id FROM public.datasets
      WHERE organization_id IN (SELECT public.user_org_ids())
    )
  );

-- ============================================================
-- 5. N8N WORKFLOWS TABLE (new, referenced by agent/tools.py)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.n8n_workflows (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id   UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  name              TEXT NOT NULL,
  workflow_json     JSONB NOT NULL,
  n8n_workflow_id   TEXT,  -- ID returned by n8n after deployment
  status            TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','inactive','draft')),
  created_by_agent  BOOLEAN NOT NULL DEFAULT true,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.n8n_workflows ENABLE ROW LEVEL SECURITY;

CREATE POLICY "n8n_workflows_select" ON public.n8n_workflows
  FOR SELECT USING (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "n8n_workflows_insert" ON public.n8n_workflows
  FOR INSERT WITH CHECK (organization_id IN (SELECT public.user_org_ids()));

-- ============================================================
-- 6. WORKFLOW TOOLS TABLE (new, referenced by agent/tools.py
--    and ViewerClient.tsx)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.workflow_tools (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  workflow_id     UUID REFERENCES public.n8n_workflows(id) ON DELETE SET NULL,
  name            TEXT NOT NULL,
  description     TEXT,
  webhook_url     TEXT NOT NULL,
  icon            TEXT DEFAULT 'wrench',
  input_schema    JSONB NOT NULL DEFAULT '{}',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.workflow_tools ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workflow_tools_select" ON public.workflow_tools
  FOR SELECT USING (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "workflow_tools_insert" ON public.workflow_tools
  FOR INSERT WITH CHECK (organization_id IN (SELECT public.user_org_ids()));

-- ============================================================
-- 7. WORKFLOW NODE SCHEMAS TABLE (new, for pgvector agent search)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.workflow_node_schemas (
  id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  node_type   TEXT NOT NULL UNIQUE,
  schema_json JSONB NOT NULL,
  description TEXT,
  embedding   vector(1536),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_nodes_embedding
  ON public.workflow_node_schemas USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- ============================================================
-- 8. FIX TABLE NAME MISMATCH: conversations router uses
--    "ai_conversations" and "ai_messages" but schema uses
--    "conversations" and "messages". Add views as aliases to
--    avoid breaking the API while the router is being fixed.
-- ============================================================
CREATE OR REPLACE VIEW public.ai_conversations AS
  SELECT * FROM public.conversations;

CREATE OR REPLACE VIEW public.ai_messages AS
  SELECT * FROM public.messages;

-- ============================================================
-- 9. REALTIME: enable for new tables
-- ============================================================
ALTER PUBLICATION supabase_realtime ADD TABLE public.processing_jobs;
ALTER PUBLICATION supabase_realtime ADD TABLE public.workflow_tools;
