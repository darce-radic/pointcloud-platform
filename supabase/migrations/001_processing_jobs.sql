-- ============================================================
-- Migration 001: processing_jobs table + tiling worker support
-- ============================================================

-- Datasets table (if not already created)
CREATE TABLE IF NOT EXISTS datasets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    project_id      UUID,
    name            TEXT NOT NULL,
    file_size       BIGINT,
    file_type       TEXT,
    s3_raw_key      TEXT,           -- R2 key for the raw uploaded file
    processed_key   TEXT,           -- R2 key for the COPC output
    copc_url        TEXT,           -- Public URL for the COPC file
    status          TEXT NOT NULL DEFAULT 'uploading'
                    CHECK (status IN ('uploading','uploaded','queued','processing','ready','failed')),
    point_count     BIGINT,
    bounds          JSONB,          -- {minx, miny, minz, maxx, maxy, maxz}
    crs             TEXT,           -- e.g. "EPSG:4326"
    metadata        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Processing jobs table
CREATE TABLE IF NOT EXISTS processing_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id      UUID NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL,
    job_type        TEXT NOT NULL DEFAULT 'tiling'
                    CHECK (job_type IN ('tiling', 'road-assets', 'bim-extraction')),
    status          TEXT NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued','processing','completed','failed','cancelled','cancelling')),
    progress_pct    INTEGER NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    input_key       TEXT,           -- R2 key of the input file (copied from dataset.s3_raw_key)
    result_url      TEXT,           -- Public URL of the output (COPC or GeoJSON etc.)
    error_message   TEXT,
    worker_id       TEXT,           -- hostname of the worker that claimed this job
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_processing_jobs_status
    ON processing_jobs (status, created_at)
    WHERE status IN ('queued', 'processing');

CREATE INDEX IF NOT EXISTS idx_processing_jobs_dataset
    ON processing_jobs (dataset_id);

CREATE INDEX IF NOT EXISTS idx_datasets_org
    ON datasets (organization_id);

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS datasets_updated_at ON datasets;
CREATE TRIGGER datasets_updated_at
    BEFORE UPDATE ON datasets
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

DROP TRIGGER IF EXISTS processing_jobs_updated_at ON processing_jobs;
CREATE TRIGGER processing_jobs_updated_at
    BEFORE UPDATE ON processing_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- Atomic job claim RPC (prevents double-processing by workers)
-- ============================================================
CREATE OR REPLACE FUNCTION claim_next_tiling_job()
RETURNS SETOF processing_jobs
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    claimed_job processing_jobs;
BEGIN
    SELECT *
    INTO claimed_job
    FROM processing_jobs
    WHERE status = 'queued'
      AND job_type = 'tiling'
    ORDER BY created_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    UPDATE processing_jobs
    SET status = 'processing',
        started_at = now(),
        updated_at = now()
    WHERE id = claimed_job.id
    RETURNING * INTO claimed_job;

    RETURN NEXT claimed_job;
END;
$$;

-- Grant execute to service_role (used by the worker)
GRANT EXECUTE ON FUNCTION claim_next_tiling_job() TO service_role;

-- Enable Row Level Security
ALTER TABLE datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE processing_jobs ENABLE ROW LEVEL SECURITY;

-- RLS: service_role bypasses all policies (used by API and worker)
-- RLS: authenticated users can only see their own org's data
CREATE POLICY "org_isolation_datasets" ON datasets
    FOR ALL TO authenticated
    USING (organization_id = (
        SELECT organization_id FROM profiles WHERE id = auth.uid()
    ));

CREATE POLICY "org_isolation_jobs" ON processing_jobs
    FOR ALL TO authenticated
    USING (organization_id = (
        SELECT organization_id FROM profiles WHERE id = auth.uid()
    ));
