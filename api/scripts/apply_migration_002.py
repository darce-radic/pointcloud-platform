"""
Apply migration 002 canonical schema additions to Supabase via the Management API.
Safe to re-run — all statements use IF NOT EXISTS / OR REPLACE.
"""
from __future__ import annotations
import os
import requests
import sys

SUPABASE_ACCESS_TOKEN = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
PROJECT_REF = "bfazarpbdrppywnofvfj"
MGMT_URL = f"https://api.supabase.com/v1/projects/{PROJECT_REF}/database/query"
HEADERS = {
    "Authorization": f"Bearer {SUPABASE_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}


def run(label: str, sql: str) -> bool:
    r = requests.post(MGMT_URL, headers=HEADERS, json={"query": sql}, timeout=30)
    if r.status_code in (200, 201):
        print(f"  ✓ {label}")
        return True
    else:
        print(f"  ✗ {label}: HTTP {r.status_code} — {r.text[:200]}")
        return False


STEPS = [
    # ── Extensions ────────────────────────────────────────────────────────────
    ("extensions: uuid-ossp", "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\""),
    ("extensions: postgis",   "CREATE EXTENSION IF NOT EXISTS \"postgis\""),
    ("extensions: vector",    "CREATE EXTENSION IF NOT EXISTS \"vector\""),

    # ── datasets: missing columns ─────────────────────────────────────────────
    ("datasets: add output columns", """
ALTER TABLE public.datasets
  ADD COLUMN IF NOT EXISTS copc_url           TEXT,
  ADD COLUMN IF NOT EXISTS dtm_url            TEXT,
  ADD COLUMN IF NOT EXISTS road_assets_url    TEXT,
  ADD COLUMN IF NOT EXISTS road_asset_stats   JSONB,
  ADD COLUMN IF NOT EXISTS ifc_url            TEXT,
  ADD COLUMN IF NOT EXISTS dxf_url            TEXT,
  ADD COLUMN IF NOT EXISTS segments_url       TEXT,
  ADD COLUMN IF NOT EXISTS bim_stats          JSONB,
  ADD COLUMN IF NOT EXISTS bounding_box       JSONB,
  ADD COLUMN IF NOT EXISTS trajectory_geojson JSONB
"""),

    # ── profiles table ────────────────────────────────────────────────────────
    ("profiles: create table", """
CREATE TABLE IF NOT EXISTS public.profiles (
  id                  UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  organization_id     UUID REFERENCES public.organizations(id) ON DELETE SET NULL,
  stripe_customer_id  TEXT,
  subscription_plan   TEXT NOT NULL DEFAULT 'trial'
                      CHECK (subscription_plan IN ('trial','starter','pro','enterprise')),
  subscription_status TEXT NOT NULL DEFAULT 'active'
                      CHECK (subscription_status IN ('active','past_due','cancelled','trialing')),
  storage_limit_bytes BIGINT NOT NULL DEFAULT 10737418240,
  storage_used_bytes  BIGINT NOT NULL DEFAULT 0,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""),

    ("profiles: RLS enable", "ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY"),

    ("profiles: select policy", """
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename='profiles' AND policyname='profiles_select_own'
  ) THEN
    CREATE POLICY profiles_select_own ON public.profiles FOR SELECT USING (id = auth.uid());
  END IF;
END $$
"""),

    ("profiles: update policy", """
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE tablename='profiles' AND policyname='profiles_update_own'
  ) THEN
    CREATE POLICY profiles_update_own ON public.profiles FOR UPDATE USING (id = auth.uid());
  END IF;
END $$
"""),

    # ── handle_new_user trigger ───────────────────────────────────────────────
    ("profiles: handle_new_user function", """
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  INSERT INTO public.profiles (id) VALUES (NEW.id) ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$
"""),

    ("profiles: on_auth_user_created trigger", """
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user()
"""),

    # ── panoramic_images table ────────────────────────────────────────────────
    ("panoramic_images: create table", """
CREATE TABLE IF NOT EXISTS public.panoramic_images (
  id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  dataset_id   UUID NOT NULL REFERENCES public.datasets(id) ON DELETE CASCADE,
  image_url    TEXT NOT NULL,
  capture_time TIMESTAMPTZ,
  geom         geometry(PointZ, 4326),
  heading      FLOAT,
  pitch        FLOAT,
  roll         FLOAT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""),

    ("panoramic_images: indexes", """
CREATE INDEX IF NOT EXISTS idx_pano_dataset ON public.panoramic_images(dataset_id);
CREATE INDEX IF NOT EXISTS idx_pano_geom    ON public.panoramic_images USING GIST(geom)
"""),

    ("panoramic_images: RLS", "ALTER TABLE public.panoramic_images ENABLE ROW LEVEL SECURITY"),

    # ── n8n_workflows table ───────────────────────────────────────────────────
    ("n8n_workflows: create table", """
CREATE TABLE IF NOT EXISTS public.n8n_workflows (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id  UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  name             TEXT NOT NULL,
  workflow_json    JSONB NOT NULL,
  n8n_workflow_id  TEXT,
  status           TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active','inactive','draft')),
  created_by_agent BOOLEAN NOT NULL DEFAULT true,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""),

    ("n8n_workflows: RLS", "ALTER TABLE public.n8n_workflows ENABLE ROW LEVEL SECURITY"),

    # ── workflow_tools: add missing columns ───────────────────────────────────
    ("workflow_tools: add required_inputs", """
ALTER TABLE public.workflow_tools
  ADD COLUMN IF NOT EXISTS required_inputs JSONB DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS is_system_tool  BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS is_active       BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS display_order   INTEGER NOT NULL DEFAULT 0
"""),

    # ── workflow_node_schemas: ensure correct schema ──────────────────────────
    ("workflow_node_schemas: add missing columns", """
ALTER TABLE public.workflow_node_schemas
  ADD COLUMN IF NOT EXISTS display_name   TEXT,
  ADD COLUMN IF NOT EXISTS category       TEXT,
  ADD COLUMN IF NOT EXISTS input_schema   JSONB,
  ADD COLUMN IF NOT EXISTS output_schema  JSONB,
  ADD COLUMN IF NOT EXISTS example_params JSONB,
  ADD COLUMN IF NOT EXISTS tags           TEXT[]
"""),

    # ── processing_jobs: ensure status check covers all worker states ─────────
    ("processing_jobs: add harmonization job_type", """
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='processing_jobs' AND column_name='progress_pct'
  ) THEN
    ALTER TABLE public.processing_jobs ADD COLUMN progress_pct SMALLINT DEFAULT 0;
  END IF;
END $$
"""),

    # ── user_org_ids helper function (used by RLS policies) ───────────────────
    ("function: user_org_ids", """
CREATE OR REPLACE FUNCTION public.user_org_ids()
RETURNS SETOF UUID LANGUAGE sql STABLE SECURITY DEFINER AS $$
  SELECT organization_id FROM public.organization_members
  WHERE user_id = auth.uid()
$$
"""),

    # ── Realtime ──────────────────────────────────────────────────────────────
    ("realtime: processing_jobs", """
DO $$
BEGIN
  BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.processing_jobs;
  EXCEPTION WHEN others THEN NULL;
  END;
END $$
"""),

    ("realtime: workflow_tools", """
DO $$
BEGIN
  BEGIN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.workflow_tools;
  EXCEPTION WHEN others THEN NULL;
  END;
END $$
"""),
]


def main():
    print(f"Applying migration 002 to project {PROJECT_REF}...\n")
    ok = 0
    fail = 0
    for label, sql in STEPS:
        if run(label, sql.strip()):
            ok += 1
        else:
            fail += 1

    print(f"\nDone. {ok} steps succeeded, {fail} failed.")

    # Verify datasets columns
    print("\nVerifying datasets columns:")
    r = requests.post(
        MGMT_URL,
        headers=HEADERS,
        json={"query": "SELECT column_name FROM information_schema.columns WHERE table_name='datasets' ORDER BY ordinal_position"},
        timeout=15,
    )
    cols = [row["column_name"] for row in r.json()]
    required = ["copc_url", "road_assets_url", "ifc_url", "dxf_url", "bim_stats", "bounding_box"]
    for col in required:
        status = "✓" if col in cols else "✗ MISSING"
        print(f"  {status} {col}")


if __name__ == "__main__":
    main()
