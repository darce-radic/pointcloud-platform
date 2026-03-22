-- ============================================================
-- Migration 2: Workflow Tools & n8n Node Schema Registry
-- Run AFTER Migration 1 in the Supabase SQL Editor
-- ============================================================

-- ============================================================
-- WORKFLOW TOOLS REGISTRY
-- Drives the dynamic toolbar in the 3D Viewer.
-- Each row = one clickable tool button.
-- ============================================================
CREATE TABLE IF NOT EXISTS public.workflow_tools (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  organization_id   UUID REFERENCES public.organizations(id) ON DELETE CASCADE,
  name              TEXT NOT NULL,
  description       TEXT NOT NULL,
  icon              TEXT NOT NULL DEFAULT 'Wrench',
  category          TEXT NOT NULL DEFAULT 'processing'
                    CHECK (category IN ('processing','analysis','export','ai','custom')),
  n8n_workflow_id   TEXT,
  job_type          TEXT,
  required_inputs   JSONB NOT NULL DEFAULT '[]',
  is_system         BOOLEAN NOT NULL DEFAULT FALSE,
  is_active         BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order        INTEGER NOT NULL DEFAULT 0,
  created_by        UUID REFERENCES auth.users(id),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_tools_org    ON public.workflow_tools(organization_id);
CREATE INDEX IF NOT EXISTS idx_workflow_tools_active ON public.workflow_tools(is_active);
CREATE INDEX IF NOT EXISTS idx_workflow_tools_system ON public.workflow_tools(is_system);

CREATE OR REPLACE TRIGGER trg_workflow_tools_updated_at
  BEFORE UPDATE ON public.workflow_tools
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.workflow_tools ENABLE ROW LEVEL SECURITY;

CREATE POLICY "workflow_tools_select" ON public.workflow_tools
  FOR SELECT USING (
    is_system = TRUE
    OR organization_id IN (SELECT public.user_org_ids())
  );

CREATE POLICY "workflow_tools_insert" ON public.workflow_tools
  FOR INSERT WITH CHECK (organization_id IN (SELECT public.user_org_ids()));

CREATE POLICY "workflow_tools_update" ON public.workflow_tools
  FOR UPDATE USING (
    organization_id IN (
      SELECT organization_id FROM public.organization_members
      WHERE user_id = auth.uid() AND role IN ('owner','admin','editor')
    )
  );

CREATE POLICY "workflow_tools_delete" ON public.workflow_tools
  FOR DELETE USING (
    organization_id IN (
      SELECT organization_id FROM public.organization_members
      WHERE user_id = auth.uid() AND role IN ('owner','admin')
    )
  );

-- ============================================================
-- N8N NODE SCHEMA REGISTRY (pgvector semantic search)
-- ============================================================
CREATE TABLE IF NOT EXISTS public.workflow_node_schemas (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  node_type       TEXT NOT NULL UNIQUE,
  display_name    TEXT NOT NULL,
  category        TEXT NOT NULL,
  description     TEXT NOT NULL,
  input_schema    JSONB NOT NULL DEFAULT '{}',
  output_schema   JSONB NOT NULL DEFAULT '{}',
  example_params  JSONB NOT NULL DEFAULT '{}',
  tags            TEXT[] NOT NULL DEFAULT '{}',
  embedding       vector(1536),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_node_schemas_category  ON public.workflow_node_schemas(category);
CREATE INDEX IF NOT EXISTS idx_node_schemas_embedding ON public.workflow_node_schemas
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

-- RPC used by AI agent for semantic node search
CREATE OR REPLACE FUNCTION public.search_nodes_by_similarity(
  query_embedding vector(1536),
  match_count     INT DEFAULT 5
)
RETURNS TABLE (
  node_type       TEXT,
  display_name    TEXT,
  category        TEXT,
  description     TEXT,
  input_schema    JSONB,
  output_schema   JSONB,
  example_params  JSONB,
  tags            TEXT[],
  similarity      FLOAT
)
LANGUAGE sql STABLE AS $$
  SELECT
    node_type, display_name, category, description,
    input_schema, output_schema, example_params, tags,
    1 - (embedding <=> query_embedding) AS similarity
  FROM public.workflow_node_schemas
  WHERE embedding IS NOT NULL
  ORDER BY embedding <=> query_embedding
  LIMIT match_count;
$$;

-- ============================================================
-- SEED: 5 system workflow tools
-- ============================================================
INSERT INTO public.workflow_tools
  (name, description, icon, category, job_type, required_inputs, is_system, is_active, sort_order)
VALUES
  ('Prepare for Viewing',
   'Convert uploaded point cloud to COPC format for fast web streaming',
   'Layers','processing','tiling','[]',TRUE,TRUE,1),
  ('Detect Road Assets',
   'Automatically detect and classify traffic signs, road markings, and drains',
   'TrafficCone','ai','road_assets',
   '[{"name":"confidence_threshold","type":"number","label":"Confidence threshold","default":0.7,"min":0.1,"max":1.0}]',
   TRUE,TRUE,2),
  ('Extract Floor Plan',
   'Generate IFC BIM model and DXF floor plan from indoor point cloud',
   'Building2','ai','bim_extraction',
   '[{"name":"floor_height","type":"number","label":"Floor height (m)","default":0.1},{"name":"ceiling_height","type":"number","label":"Ceiling height (m)","default":2.8}]',
   TRUE,TRUE,3),
  ('Generate DTM',
   'Create a Digital Terrain Model from classified ground points',
   'Mountain','processing','dtm_generation',
   '[{"name":"resolution","type":"number","label":"Resolution (m)","default":0.5,"min":0.05,"max":10.0}]',
   TRUE,TRUE,4),
  ('Generate Asset Report',
   'Export a PDF inventory report of all detected features in this dataset',
   'FileText','export','custom_workflow',
   '[{"name":"include_images","type":"boolean","label":"Include feature images","default":true}]',
   TRUE,TRUE,5)
ON CONFLICT DO NOTHING;

-- ============================================================
-- SEED: n8n node schema registry
-- ============================================================
INSERT INTO public.workflow_node_schemas
  (node_type, display_name, category, description, input_schema, output_schema, example_params, tags)
VALUES
  ('pdal.read_s3','Read Point Cloud from S3','point_cloud',
   'Read a LAS, LAZ, or COPC point cloud file from an S3 bucket into the processing pipeline',
   '{"s3_key":{"type":"string","required":true}}','{"point_cloud":{"type":"pdal_pipeline"}}',
   '{"s3_key":"datasets/abc123/raw.laz"}',
   ARRAY['read','input','s3','las','laz','copc','load']),

  ('pdal.crop','Crop / Clip Point Cloud','point_cloud',
   'Clip a point cloud to a bounding box or polygon geometry, removing all points outside the boundary',
   '{"bounds":{"type":"string"}}','{"point_cloud":{"type":"pdal_pipeline"}}',
   '{"bounds":"([0,100],[0,100],[0,50])"}',
   ARRAY['crop','clip','filter','boundary','polygon','bbox','area']),

  ('pdal.reproject','Reproject / Transform CRS','point_cloud',
   'Reproject point cloud coordinates from one coordinate reference system to another using PROJ',
   '{"in_srs":{"type":"string","required":true},"out_srs":{"type":"string","required":true}}',
   '{"point_cloud":{"type":"pdal_pipeline"}}','{"in_srs":"EPSG:32755","out_srs":"EPSG:4326"}',
   ARRAY['reproject','crs','coordinate','transform','epsg','proj','georeference']),

  ('pdal.ground_classify','Classify Ground Points','point_cloud',
   'Identify and classify ground points using the SMRF (Simple Morphological Filter) algorithm',
   '{"slope":{"type":"number","default":0.15},"window":{"type":"number","default":18}}',
   '{"point_cloud":{"type":"pdal_pipeline"}}','{"slope":0.15,"window":18}',
   ARRAY['ground','classify','smrf','dtm','terrain','filter','lidar']),

  ('pdal.noise_remove','Remove Noise Points','point_cloud',
   'Remove statistical outlier noise points using k-nearest neighbour analysis',
   '{"mean_k":{"type":"integer","default":8},"multiplier":{"type":"number","default":2.0}}',
   '{"point_cloud":{"type":"pdal_pipeline"}}','{"mean_k":8,"multiplier":2.0}',
   ARRAY['noise','outlier','clean','filter','statistical','knn','denoise']),

  ('pdal.decimate','Decimate / Thin Point Cloud','point_cloud',
   'Reduce point cloud density by keeping every Nth point or voxel grid subsampling',
   '{"step":{"type":"integer","default":10},"method":{"type":"string","default":"every_nth"}}',
   '{"point_cloud":{"type":"pdal_pipeline"}}','{"step":10}',
   ARRAY['decimate','thin','downsample','reduce','density','voxel','subsample']),

  ('pdal.write_copc','Write COPC (Cloud Optimized Point Cloud)','point_cloud',
   'Write the processed point cloud to COPC LAZ format on S3 for web streaming',
   '{"s3_key":{"type":"string","required":true}}',
   '{"s3_key":{"type":"string"},"copc_url":{"type":"string"}}',
   '{"s3_key":"datasets/abc123/processed.copc.laz"}',
   ARRAY['write','output','copc','laz','s3','stream','tile','publish']),

  ('pdal.dtm','Generate DTM Raster','point_cloud',
   'Generate a Digital Terrain Model GeoTIFF raster from classified ground points',
   '{"resolution":{"type":"number","default":0.5}}','{"geotiff_s3_key":{"type":"string"}}',
   '{"resolution":0.5}',
   ARRAY['dtm','dem','terrain','raster','geotiff','elevation','ground','surface']),

  ('ai.road_assets','Detect Road Assets (AI)','ai',
   'Use OpenPCDet 3D object detection to find traffic signs, road markings, drains, and kerbs',
   '{"confidence_threshold":{"type":"number","default":0.7}}',
   '{"geojson_s3_key":{"type":"string"},"feature_count":{"type":"integer"}}',
   '{"confidence_threshold":0.7}',
   ARRAY['road','traffic','sign','marking','drain','detect','ai','ml','classify','infrastructure']),

  ('ai.bim_extraction','Extract BIM / Floor Plan (AI)','ai',
   'Use Cloud2BIM to segment walls, floors, ceilings, doors and windows and output IFC and DXF files',
   '{"floor_height":{"type":"number","default":0.1},"ceiling_height":{"type":"number","default":2.8}}',
   '{"ifc_s3_key":{"type":"string"},"dxf_s3_key":{"type":"string"}}',
   '{"floor_height":0.1,"ceiling_height":2.8}',
   ARRAY['bim','ifc','dxf','floor plan','room','wall','door','window','indoor','building','cad']),

  ('geo.georeference','Georeference with GCPs','point_cloud',
   'Apply ground control points to georeference a SLAM point cloud using rubber-sheeting transformation',
   '{"gcps":{"type":"array"},"method":{"type":"string","default":"tps"}}',
   '{"point_cloud":{"type":"pdal_pipeline"}}',
   '{"gcps":[{"source":[10.5,20.3,1.2],"target":[151.2093,-33.8688,45.0]}],"method":"tps"}',
   ARRAY['georeference','gcp','control point','slam','transform','coordinate','align','register']),

  ('notify.webhook','Send Webhook Notification','utility',
   'Send an HTTP POST notification to a webhook URL when the workflow completes',
   '{"url":{"type":"string","required":true}}','{"status":{"type":"string"}}',
   '{"url":"https://hooks.example.com/notify"}',
   ARRAY['notify','webhook','http','callback','alert','complete','trigger'])

ON CONFLICT (node_type) DO NOTHING;
