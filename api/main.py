"""
PointCloud Platform — FastAPI Application Entry Point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from config import settings

from routers import datasets, conversations, organizations, projects, jobs, billing, workflow_tools, stac
from agent import graph as agent_graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    print(f"Starting PointCloud Platform API [{settings.ENVIRONMENT}]")
    yield
    print("Shutting down PointCloud Platform API")


# ── CORS origins ──────────────────────────────────────────────────────────────
# ALLOWED_ORIGINS env var accepts a comma-separated list of origins.
# In development mode, localhost:3000 and localhost:5173 are added automatically.
_base_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
if settings.ENVIRONMENT != "production":
    _base_origins += ["http://localhost:3000", "http://localhost:5173"]
# Always include the configured APP_DOMAIN
if settings.APP_DOMAIN and settings.APP_DOMAIN not in _base_origins:
    _base_origins.append(settings.APP_DOMAIN)

app = FastAPI(
    title="PointCloud Platform API",
    version="1.0.0",
    description="Multi-tenant cloud API for 3D point cloud processing and visualization.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_base_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ──────────────────────────────────────────────────────────
app.include_router(organizations.router, prefix="/api/v1", tags=["Organizations"])
app.include_router(projects.router, prefix="/api/v1", tags=["Projects"])
app.include_router(datasets.router, prefix="/api/v1", tags=["Datasets"])
app.include_router(jobs.router, prefix="/api/v1", tags=["Jobs"])
app.include_router(conversations.router, prefix="/api/v1", tags=["AI"])
app.include_router(billing.router, prefix="/api/v1", tags=["Billing"])
app.include_router(workflow_tools.router, prefix="/api/v1", tags=["Workflow Tools"])
app.include_router(stac.router, prefix="/api/v1", tags=["STAC Catalogue"])
app.include_router(agent_graph.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
