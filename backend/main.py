"""Historiador — Multi-Agent History Generator"""
import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import init_db
from backend.services.app_config_service import get_app_config_service
from backend.routers import topics, profiles, histories, pipeline, notifications, config


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and config on startup."""
    await init_db()
    svc = get_app_config_service()
    await svc.seed_defaults()
    yield
    from backend.database import engine
    await engine.dispose()


app = FastAPI(
    title="Historiador",
    description="Multi-Agent History Generation System",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(",") if settings.cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(topics.router)
app.include_router(profiles.router)
app.include_router(histories.router)
app.include_router(pipeline.router)
app.include_router(notifications.router)
app.include_router(config.router)

# Serve frontend static files
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")