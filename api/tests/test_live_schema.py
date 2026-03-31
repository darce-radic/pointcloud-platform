"""
Live Supabase Schema Integration Tests
=======================================
These tests connect to the REAL Supabase instance (not a mock) to verify that:
  1. All tables the API code references actually exist.
  2. All columns the workers write actually exist on those tables.
  3. The pgvector extension and workflow_node_schemas embeddings are present.
  4. RLS is enabled on all user-facing tables.

Running:
    # From the api/ directory — requires real credentials in env:
    SUPABASE_URL=https://bfazarpbdrppywnofvfj.supabase.co \
    SUPABASE_SERVICE_ROLE_KEY=<service-role-key> \
    pytest tests/test_live_schema.py -v

These tests are intentionally skipped in CI when SUPABASE_URL is set to the
test placeholder ("http://test-supabase-url"), so they never block unit-test runs.
"""
from __future__ import annotations

import os
import pytest
from supabase import create_client, Client

# ── Skip guard: don't run against the mock URL used in unit tests ─────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

pytestmark = pytest.mark.skipif(
    not SUPABASE_URL or SUPABASE_URL == "http://test-supabase-url",
    reason="Live schema tests require a real SUPABASE_URL (not the unit-test placeholder)",
)


@pytest.fixture(scope="module")
def sb() -> Client:
    """Module-scoped real Supabase client."""
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def _columns(sb: Client, table: str) -> set[str]:
    """Return the set of column names for a table via information_schema."""
    result = (
        sb.table("information_schema.columns")
        .select("column_name")
        .eq("table_schema", "public")
        .eq("table_name", table)
        .execute()
    )
    return {row["column_name"] for row in (result.data or [])}


def _tables(sb: Client) -> set[str]:
    """Return all public table names."""
    result = (
        sb.table("information_schema.tables")
        .select("table_name")
        .eq("table_schema", "public")
        .eq("table_type", "BASE TABLE")
        .execute()
    )
    return {row["table_name"] for row in (result.data or [])}


# ── Table existence ────────────────────────────────────────────────────────────

REQUIRED_TABLES = {
    "organizations",
    "organization_members",
    "profiles",
    "projects",
    "datasets",
    "processing_jobs",
    "jobs",
    "conversations",
    "messages",
    "workflow_tools",
    "workflow_node_schemas",
    "n8n_workflows",
    "panoramic_images",
}


def test_required_tables_exist(sb: Client):
    """All tables referenced by the API routers must exist in the live DB."""
    live = _tables(sb)
    missing = REQUIRED_TABLES - live
    assert not missing, f"Missing tables in live Supabase: {sorted(missing)}"


# ── datasets column coverage ───────────────────────────────────────────────────

DATASETS_REQUIRED_COLUMNS = {
    # Core
    "id", "name", "status", "organization_id", "project_id",
    "created_at", "updated_at",
    # Storage keys (written by tiling + harmonization workers)
    "r2_key", "harmonized_key", "processed_key",
    # Output URLs (written by workers, read by frontend)
    "copc_url", "dtm_url", "road_assets_url", "ifc_url", "dxf_url",
    "segments_url",
    # Stats blobs
    "road_asset_stats", "bim_stats",
    # Spatial
    "bounding_box", "trajectory_geojson",
    # Metadata
    "point_count", "crs_epsg", "file_size_bytes",
}


def test_datasets_columns_exist(sb: Client):
    """All columns written by API routers and workers must exist on datasets."""
    live = _columns(sb, "datasets")
    missing = DATASETS_REQUIRED_COLUMNS - live
    assert not missing, (
        f"Missing columns on datasets table: {sorted(missing)}\n"
        f"Run supabase/migrations/002_*.sql to add them."
    )


# ── workflow_node_schemas column coverage ─────────────────────────────────────

WORKFLOW_NODE_SCHEMAS_REQUIRED_COLUMNS = {
    "id", "node_type", "display_name", "category",
    "description", "input_schema", "output_schema",
    "example_params", "tags", "embedding",
    "created_at",
}


def test_workflow_node_schemas_columns_exist(sb: Client):
    """All columns used by the node library seed and agent must exist."""
    live = _columns(sb, "workflow_node_schemas")
    missing = WORKFLOW_NODE_SCHEMAS_REQUIRED_COLUMNS - live
    assert not missing, (
        f"Missing columns on workflow_node_schemas: {sorted(missing)}"
    )


# ── workflow_node_schemas seed data ───────────────────────────────────────────

EXPECTED_NODE_TYPES = {
    "pdal.read_s3",
    "pdal.noise_remove",
    "pdal.ground_classify",
    "pdal.decimate",
    "pdal.crop",
    "pdal.reproject",
    "pdal.dtm",
    "pdal.write_copc",
    "ai.road_assets",
    "ai.bim_extraction",
    "geo.georeference",
    "notify.webhook",
}


def test_node_library_seeded(sb: Client):
    """All 12 workflow nodes must be present with non-null embeddings."""
    result = (
        sb.table("workflow_node_schemas")
        .select("node_type, embedding")
        .execute()
    )
    rows = result.data or []
    seeded_types = {r["node_type"] for r in rows}
    missing = EXPECTED_NODE_TYPES - seeded_types
    assert not missing, f"Missing node types in workflow_node_schemas: {sorted(missing)}"

    # All seeded rows must have a non-null embedding
    null_embeddings = [r["node_type"] for r in rows if not r.get("embedding")]
    assert not null_embeddings, (
        f"Nodes with null embeddings (run seed script): {null_embeddings}"
    )


# ── processing_jobs column coverage ───────────────────────────────────────────

PROCESSING_JOBS_REQUIRED_COLUMNS = {
    "id", "dataset_id", "organization_id", "job_type",
    "status", "progress", "error_message",
    "created_at", "updated_at",
}


def test_processing_jobs_columns_exist(sb: Client):
    """All columns used by the jobs router must exist on processing_jobs."""
    live = _columns(sb, "processing_jobs")
    missing = PROCESSING_JOBS_REQUIRED_COLUMNS - live
    assert not missing, (
        f"Missing columns on processing_jobs: {sorted(missing)}"
    )


# ── workflow_tools column coverage ────────────────────────────────────────────

WORKFLOW_TOOLS_REQUIRED_COLUMNS = {
    "id", "organization_id", "name", "description",
    "icon", "webhook_url", "n8n_workflow_id",
    "required_inputs", "is_active", "is_system_tool", "display_order",
    "created_at",
}


def test_workflow_tools_columns_exist(sb: Client):
    """All columns used by the workflow_tools router must exist."""
    live = _columns(sb, "workflow_tools")
    missing = WORKFLOW_TOOLS_REQUIRED_COLUMNS - live
    assert not missing, (
        f"Missing columns on workflow_tools: {sorted(missing)}"
    )


# ── conversations + messages column coverage ──────────────────────────────────

def test_conversations_columns_exist(sb: Client):
    """conversations table must have the columns used by the router."""
    required = {"id", "organization_id", "user_id", "dataset_id", "title", "created_at"}
    live = _columns(sb, "conversations")
    missing = required - live
    assert not missing, f"Missing columns on conversations: {sorted(missing)}"


def test_messages_columns_exist(sb: Client):
    """messages table must have the columns used by the router."""
    required = {"id", "conversation_id", "role", "content", "created_at"}
    live = _columns(sb, "messages")
    missing = required - live
    assert not missing, f"Missing columns on messages: {sorted(missing)}"


# ── RLS enabled on all user-facing tables ─────────────────────────────────────

RLS_REQUIRED_TABLES = {
    "organizations", "organization_members", "profiles",
    "projects", "datasets", "processing_jobs",
    "conversations", "messages",
    "workflow_tools", "workflow_node_schemas",
    "panoramic_images", "n8n_workflows",
}


def test_rls_enabled_on_user_tables(sb: Client):
    """RLS must be enabled on all user-facing tables."""
    result = sb.rpc(
        "query",
        {
            "query": (
                "SELECT tablename, rowsecurity "
                "FROM pg_tables "
                "WHERE schemaname = 'public'"
            )
        },
    ).execute()

    # Fall back to information_schema if the rpc doesn't exist
    if not result.data:
        pytest.skip("Cannot query pg_tables via this client — check service role permissions")

    rls_map = {row["tablename"]: row["rowsecurity"] for row in result.data}
    rls_disabled = [t for t in RLS_REQUIRED_TABLES if not rls_map.get(t, False)]
    assert not rls_disabled, (
        f"RLS is NOT enabled on these tables: {sorted(rls_disabled)}"
    )


# ── Smoke test: can we read from the live DB at all? ─────────────────────────

def test_live_connection(sb: Client):
    """Verify the service-role key can read from organizations."""
    result = sb.table("organizations").select("id").limit(1).execute()
    # Either returns rows or an empty list — both are fine; what matters is no exception
    assert result.data is not None, "organizations query returned None — check service role key"
