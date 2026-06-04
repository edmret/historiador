"""Historiador — Multi-Agent History Generator"""
import os
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.database import init_db
from backend.services.app_config_service import get_app_config_service
from backend.routers import topics, profiles, histories, pipeline, notifications, config, auth

_mcp_process = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and config on startup. Optionally launch MCP server."""
    await init_db()
    svc = get_app_config_service()
    await svc.seed_defaults()

    # Start MCP server subprocess if enabled
    global _mcp_process
    if settings.mcp_enabled:
        _mcp_process = await _start_mcp_server()

    yield

    # Cleanup
    if _mcp_process:
        _mcp_process.terminate()
        try:
            await asyncio.wait_for(_mcp_process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            _mcp_process.kill()

    from backend.database import engine
    await engine.dispose()


async def _start_mcp_server():
    """Launch the MCP server as a subprocess on the configured port."""
    import sys

    mcp_script = Path(__file__).resolve().parent / "mcp_server.py"
    if not mcp_script.exists():
        print(f"⚠️  MCP server script not found at {mcp_script}")
        return None

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(mcp_script),
        f"--port={settings.mcp_port}",
        f"--host={settings.mcp_host}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    print(f"🔌 MCP server started on {settings.mcp_host}:{settings.mcp_port} (pid={proc.pid})")
    return proc


# ── Auth Middleware ──────────────────────────────────────────────────────────

async def auth_translation_middleware(request: Request, call_next):
    """Translate x-api-key header into request.state for downstream deps.

    Also sets request.state.authenticated_user if a valid Bearer token or
    x-api-key is found, so route handlers can use it without calling Stytch twice.
    """
    # Check x-api-key header first
    api_key = request.headers.get("x-api-key", "")
    if api_key:
        from backend.auth.tokens import resolve_api_token
        user = await resolve_api_token(api_key)
        if user:
            request.state.api_user = user
            request.state.authenticated_user = user

    # Check Authorization: Bearer *** (standard Stytch JWT)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and not getattr(request.state, "authenticated_user", None):
        jwt = auth_header[7:]
        from backend.auth.stytch_client import validate_stytch_session
        user = await validate_stytch_session(jwt)
        if user:
            request.state.authenticated_user = user

    # Dev mode: no Stytch configured
    if not getattr(request.state, "authenticated_user", None):
        if not settings.stytch_project_id or not settings.stytch_secret:
            request.state.authenticated_user = {"user_id": "anonymous", "email": None, "name": "Developer"}
            request.state.api_user = request.state.authenticated_user

    response = await call_next(request)
    return response


# ── Main App ─────────────────────────────────────────────────────────────────

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
app.middleware("http")(auth_translation_middleware)

app.include_router(topics.router)
app.include_router(profiles.router)
app.include_router(histories.router)
app.include_router(pipeline.router)
app.include_router(notifications.router)
app.include_router(config.router)
app.include_router(auth.router)

# Serve frontend static files
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")