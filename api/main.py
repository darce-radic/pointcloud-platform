"""
PointCloud Platform — FastAPI Application Entry Point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from config import settings

from routers import datasets, conversations, organizations, projects, jobs
from agent import graph as agent_graph


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    print(f"Starting PointCloud Platform API [{settings.ENVIRONMENT}]")
    yield
    print("Shutting down PointCloud Platform API")


app = FastAPI(
    title="PointCloud Platform API",
    version="1.0.0",
    description="Multi-tenant cloud API for 3D point cloud processing and visualization.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.APP_DOMAIN, "http://localhost:5173"],
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
app.include_router(agent_graph.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
