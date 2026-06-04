#!/usr/bin/env python3
"""Historiador MCP Server — exposes all UI operations as MCP tools.

Usage:
    python3 backend/mcp_server.py                # stdio transport (default)
    python3 backend/mcp_server.py --sse          # SSE transport on :8081
    python3 backend/mcp_server.py --port=8081    # customize SSE port

Authentication:
  - stdio mode: no auth (localhost only, same security boundary)
  - SSE mode: requires Authorization: Bearer *** header
    (Stytch session JWT or long-lived API token via x-api-key)
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Imports ──────────────────────────────────────────────────────────────────

from mcp.server.fastmcp import FastMCP
from backend.config import settings
from backend.database import init_db, async_session, get_session
from backend.services.app_config_service import get_app_config_service
from backend.auth.stytch_client import validate_stytch_session
from backend.auth.tokens import resolve_api_token, create_api_token, list_api_tokens, revoke_api_token

# Agent imports
from backend.agents.orchestrator import HistoriadorOrchestrator
from backend.agents.scoping_agent import ScopingAgent
from backend.llm_client import LLMClient

# Model imports (for queries)
from backend.models.topic import Topic
from backend.models.subtopic import Subtopic
from backend.models.scoping_message import ScopingMessage
from backend.models.history import History
from backend.models.api_token import APIToken
from sqlalchemy import select


# ── Metadata ─────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "Historiador",
    instructions="Multi-Agent History Generation System — MCP interface",
)


# ── Auth Context ─────────────────────────────────────────────────────────────

class MCPContext:
    """Holds the authenticated user for the current request."""

    def __init__(self, user_id: str = "anonymous", email: str | None = None, name: str | None = None):
        self.user_id = user_id
        self.email = email
        self.name = name

    @property
    def is_authenticated(self) -> bool:
        return self.user_id != "anonymous"

    def __repr__(self):
        return f"MCPContext(user_id={self.user_id}, email={self.email})"


_current_context: MCPContext = MCPContext()


async def _get_db_session():
    """Get an async DB session."""
    async with async_session() as session:
        yield session


# ── Tools ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def create_topic(title: str) -> dict:
    """Create a new history topic.

    Args:
        title: The title/description of the history topic

    Returns:
        A dict with the created topic's id, title, and status
    """
    async with async_session() as session:
        topic = Topic(title=title, status="scoping")
        session.add(topic)
        await session.commit()
        await session.refresh(topic)
        return {"id": topic.id, "title": topic.title, "status": topic.status, "created_at": topic.created_at.isoformat() if topic.created_at else None}


@mcp.tool()
async def list_topics() -> list[dict]:
    """List all history topics.

    Returns:
        A list of topics with id, title, status, and timestamps
    """
    async with async_session() as session:
        result = await session.execute(select(Topic).order_by(Topic.created_at.desc()))
        topics = result.scalars().all()
        return [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "num_subtopics": len(t.subtopics) if hasattr(t, "subtopics") else 0,
            }
            for t in topics
        ]


@mcp.tool()
async def get_topic(topic_id: int) -> dict:
    """Get a topic with its subtopics.

    Args:
        topic_id: The topic's numeric ID

    Returns:
        Full topic details including subtopics
    """
    async with async_session() as session:
        result = await session.execute(select(Topic).where(Topic.id == topic_id))
        topic = result.scalar_one_or_none()
        if not topic:
            return {"error": f"Topic {topic_id} not found"}
        return {
            "id": topic.id,
            "title": topic.title,
            "status": topic.status,
            "created_at": topic.created_at.isoformat() if topic.created_at else None,
            "subtopics": [
                {"id": s.id, "title": s.title, "description": s.description, "status": s.status}
                for s in (topic.subtopics or [])
            ],
        }


@mcp.tool()
async def send_scoping_message(topic_id: int, message: str) -> dict:
    """Send a scoping message to refine a topic. Ends scoping when user types 'done'.

    Args:
        topic_id: The topic ID
        message: Your message to the scoping agent (topic refinement, questions, or "done")

    Returns:
        The agent's response and whether scoping is complete
    """
    async with async_session() as session:
        result = await session.execute(select(Topic).where(Topic.id == topic_id))
        topic = result.scalar_one_or_none()
        if not topic:
            return {"error": f"Topic {topic_id} not found"}

        # Get LLM config
        svc = get_app_config_service()
        agent_cfg = await svc.get_agent_config("scoping")
        llm_client = LLMClient(config=agent_cfg)
        agent = ScopingAgent(llm_client=llm_client)

        # Get conversation history
        history_result = await session.execute(
            select(ScopingMessage).where(ScopingMessage.topic_id == topic_id).order_by(ScopingMessage.created_at)
        )
        messages = history_result.scalars().all()
        history = [{"role": m.role, "content": m.content} for m in messages]

        # Run scoping agent
        response_data = await agent.process_response(history, message)
        response = response_data["agent_message"]

        # Save user and agent messages
        user_msg = ScopingMessage(topic_id=topic_id, role="user", content=message)
        agent_msg = ScopingMessage(topic_id=topic_id, role="assistant", content=response)
        session.add_all([user_msg, agent_msg])
        await session.commit()

        # Check if scoping is complete
        is_done = message.strip().lower() == "done" or "[SCOPING_COMPLETE]" in response

        return {
            "response": response,
            "scoping_complete": is_done,
            "message_id": agent_msg.id,
        }


@mcp.tool()
async def get_scoping_messages(topic_id: int) -> list[dict]:
    """Get the scoping conversation for a topic.

    Args:
        topic_id: The topic ID

    Returns:
        The conversation history
    """
    async with async_session() as session:
        result = await session.execute(
            select(ScopingMessage).where(ScopingMessage.topic_id == topic_id).order_by(ScopingMessage.created_at)
        )
        messages = result.scalars().all()
        return [
            {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat() if m.created_at else None}
            for m in messages
        ]


@mcp.tool()
async def update_subtopic(topic_id: int, subtopic_id: int, status: str) -> dict:
    """Update a subtopic's status (selected/excluded).

    Args:
        topic_id: The topic ID
        subtopic_id: The subtopic ID
        status: New status — "selected", "excluded", or "pending"

    Returns:
        Updated subtopic info
    """
    async with async_session() as session:
        result = await session.execute(
            select(Subtopic).where(Subtopic.id == subtopic_id, Subtopic.topic_id == topic_id)
        )
        sub = result.scalar_one_or_none()
        if not sub:
            return {"error": f"Subtopic {subtopic_id} not found"}
        sub.status = status
        await session.commit()
        return {"id": sub.id, "title": sub.title, "status": sub.status}


@mcp.tool()
async def run_pipeline(
    topic_id: int,
    num_histories: int | None = None,
    num_research_agents: int | None = None,
) -> dict:
    """Run the full history generation pipeline for a topic.

    Args:
        topic_id: The topic ID
        num_histories: Number of histories to generate (default: from config)
        num_research_agents: Number of parallel research agents (default: from config)

    Returns:
        Pipeline status with info about generated histories
    """
    svc = get_app_config_service()
    config = await svc.get_config()

    n_histories = num_histories or int(config.get("default_num_histories", 2))
    n_research = num_research_agents or int(config.get("default_num_research_agents", 3))

    orchestrator = HistoriadorOrchestrator()
    async with async_session() as session:
        result = await session.execute(select(Topic).where(Topic.id == topic_id))
        topic = result.scalar_one_or_none()
        if not topic:
            return {"error": f"Topic {topic_id} not found"}

        result = await orchestrator.run_pipeline(
            topic_id=str(topic_id),
            num_histories=n_histories,
            num_research_agents=n_research,
        )
        return {
            "topic_id": topic_id,
            "topic_title": topic.title,
            "histories_generated": len(result.get("histories", [])),
            "histories": result.get("histories", []),
            "status": "completed",
        }


@mcp.tool()
async def get_pipeline_status(topic_id: int) -> dict:
    """Get the pipeline generation status for a topic.

    Args:
        topic_id: The topic ID

    Returns:
        Pipeline progress including generated histories
    """
    async with async_session() as session:
        topic_result = await session.execute(select(Topic).where(Topic.id == topic_id))
        topic = topic_result.scalar_one_or_none()
        if not topic:
            return {"error": f"Topic {topic_id} not found"}

        history_result = await session.execute(
            select(History).where(History.topic_id == topic_id).order_by(History.created_at)
        )
        histories = history_result.scalars().all()
        return {
            "topic_id": topic_id,
            "topic_title": topic.title,
            "topic_status": topic.status,
            "total_histories": len(histories),
            "histories": [
                {"id": h.id, "title": h.title, "status": h.status, "created_at": h.created_at.isoformat() if h.created_at else None}
                for h in histories
            ],
        }


@mcp.tool()
async def list_histories(topic_id: int | None = None, status: str | None = None) -> list[dict]:
    """List generated histories, optionally filtered.

    Args:
        topic_id: Filter by topic ID (optional)
        status: Filter by status — "in_review", "accepted", "rejected", "refining" (optional)

    Returns:
        List of histories
    """
    async with async_session() as session:
        stmt = select(History)
        if topic_id is not None:
            stmt = stmt.where(History.topic_id == topic_id)
        if status:
            stmt = stmt.where(History.status == status)
        stmt = stmt.order_by(History.created_at.desc())
        result = await session.execute(stmt)
        histories = result.scalars().all()
        return [
            {
                "id": h.id,
                "title": h.title,
                "topic_id": h.topic_id,
                "status": h.status,
                "tone": h.tone,
                "audience": h.audience,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in histories
        ]


@mcp.tool()
async def get_history(history_id: int) -> dict:
    """Get the full content of a generated history.

    Args:
        history_id: The history ID

    Returns:
        Full history with content and metadata
    """
    async with async_session() as session:
        result = await session.execute(select(History).where(History.id == history_id))
        h = result.scalar_one_or_none()
        if not h:
            return {"error": f"History {history_id} not found"}
        return {
            "id": h.id,
            "title": h.title,
            "content": h.content,
            "topic_id": h.topic_id,
            "status": h.status,
            "tone": h.tone,
            "audience": h.audience,
            "profile_id": h.profile_id,
            "created_at": h.created_at.isoformat() if h.created_at else None,
            "feedback": [
                {"type": f.feedback_type, "text": f.feedback_text, "created_at": f.created_at.isoformat() if f.created_at else None}
                for f in (h.feedback or [])
            ],
        }


@mcp.tool()
async def submit_feedback(history_id: int, feedback_type: str, feedback_text: str | None = None) -> dict:
    """Submit feedback on a generated history.

    Args:
        history_id: The history ID
        feedback_type: "accept", "reject", or "refine"
        feedback_text: Optional feedback text (required for "refine")

    Returns:
        Updated history status
    """
    orchestrator = HistoriadorOrchestrator()
    result = await orchestrator.submit_feedback(str(history_id), feedback_type, feedback_text)
    if "error" in result:
        return result
    return {"id": history_id, "status": result.get("status"), "feedback_type": feedback_type}


@mcp.tool()
async def list_profiles() -> list[dict]:
    """List all writing profiles.

    Returns:
        List of profiles with tone, audience, length settings
    """
    async with async_session() as session:
        result = await session.execute(select(Profile).order_by(Profile.name))
        profiles = result.scalars().all()
        return [
            {
                "id": p.id,
                "name": p.name,
                "tone": p.tone,
                "audience": p.audience,
                "length": p.length,
                "style_notes": p.style_notes,
            }
            for p in profiles
        ]


@mcp.tool()
async def create_profile(name: str, tone: str = "neutral", audience: str = "general", length: str = "medium", style_notes: str = "") -> dict:
    """Create a new writing profile.

    Args:
        name: Profile name
        tone: Writing tone — "neutral", "dramatic", "educational", "humorous", "epic"
        audience: Target audience — "general", "academic", "young", "expert"
        length: Target length — "short" (~300w), "medium" (~800w), "long" (~1500w)
        style_notes: Custom style preferences (optional)

    Returns:
        The created profile
    """
    async with async_session() as session:
        profile = Profile(name=name, tone=tone, audience=audience, length=length, style_notes=style_notes)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
        return {"id": profile.id, "name": profile.name, "tone": profile.tone, "audience": profile.audience, "length": profile.length}


@mcp.tool()
async def update_profile(profile_id: int, name: str | None = None, tone: str | None = None, audience: str | None = None, length: str | None = None, style_notes: str | None = None) -> dict:
    """Update an existing writing profile.

    Args:
        profile_id: The profile ID
        name: New name (optional)
        tone: New tone (optional)
        audience: New audience (optional)
        length: New length (optional)
        style_notes: New style notes (optional)

    Returns:
        Updated profile
    """
    async with async_session() as session:
        result = await session.execute(select(Profile).where(Profile.id == profile_id))
        p = result.scalar_one_or_none()
        if not p:
            return {"error": f"Profile {profile_id} not found"}
        if name is not None: p.name = name
        if tone is not None: p.tone = tone
        if audience is not None: p.audience = audience
        if length is not None: p.length = length
        if style_notes is not None: p.style_notes = style_notes
        await session.commit()
        return {"id": p.id, "name": p.name, "tone": p.tone, "audience": p.audience, "length": p.length}


@mcp.tool()
async def get_config() -> dict:
    """Get application configuration (API keys masked).

    Returns:
        Current configuration as a flat dict with sensitive values masked
    """
    svc = get_app_config_service()
    config = await svc.get_config()
    # Mask sensitive keys
    masked_keys = ["llm_api_key", "tavily_api_key", "serpapi_api_key", "vapid_private_key"]
    for key in masked_keys:
        if key in config and config[key]:
            val = config[key]
            config[key] = (val[:4] + "..." + val[-4:]) if len(val) > 8 else "****"
    return config


@mcp.tool()
async def update_config(**kwargs) -> dict:
    """Update application configuration.

    Args:
        kwargs: Key-value pairs to update (e.g., llm_base_url="https://...", llm_model="gpt-4")

    Returns:
        Updated configuration
    """
    svc = get_app_config_service()
    updated = await svc.update_config(kwargs)
    # Mask sensitive keys
    masked_keys = ["llm_api_key", "tavily_api_key", "serpapi_api_key", "vapid_private_key"]
    for key in masked_keys:
        if key in updated and updated[key]:
            val = updated[key]
            updated[key] = (val[:4] + "..." + val[-4:]) if len(val) > 8 else "****"
    return updated


@mcp.tool()
async def test_llm(base_url: str, api_key: str, model: str) -> dict:
    """Test an LLM connection.

    Args:
        base_url: OpenAI-compatible base URL
        api_key: API key
        model: Model name

    Returns:
        {"success": bool, "message": str}
    """
    svc = get_app_config_service()
    success, message = await svc.test_llm_connection(base_url, api_key, model)
    return {"success": success, "message": message}


@mcp.tool()
async def create_api_token_tool(label: str) -> dict:
    """Generate a new long-lived API token for programmatic access.

    Args:
        label: A human-readable label for this token

    Returns:
        The raw token (shown once) and its metadata

    Note:
        The raw token is only returned once. Save it securely.
    """
    # In MCP context, use a synthetic user_id since we're not authenticated
    raw, token = await create_api_token(label, "mcp-user")
    return {"raw_token": raw, "id": token.id, "label": token.label}


@mcp.tool()
async def list_api_tokens_tool() -> list[dict]:
    """List all active API tokens.

    Returns:
        List of API tokens (without the secret values)
    """
    return await list_api_tokens("mcp-user")


@mcp.tool()
async def revoke_api_token_tool(token_id: str) -> dict:
    """Revoke an API token.

    Args:
        token_id: The token ID to revoke

    Returns:
        {"success": bool}
    """
    ok = await revoke_api_token(token_id, "mcp-user")
    return {"success": ok}


@mcp.tool()
async def get_agent_config(agent_type: str) -> dict:
    """Get LLM configuration for a specific agent.

    Args:
        agent_type: Agent type — "scoping", "research", "compiler", "writer", "editor", "profile"

    Returns:
        Agent config with base_url, model (api_key masked)
    """
    svc = get_app_config_service()
    try:
        cfg = await svc.get_agent_config(agent_type)
        key = cfg.get("api_key", "")
        if key:
            cfg["api_key"] = (key[:4] + "..." + key[-4:]) if len(key) > 8 else "****"
        return cfg
    except ValueError as e:
        return {"error": str(e)}


@mcp.tool()
async def health() -> dict:
    """Check if the MCP server is healthy and the database is accessible.

    Returns:
        Health status with database connectivity info
    """
    try:
        async with async_session() as session:
            await session.execute(select(Topic).limit(1))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


# ── Auth Middleware for SSE ──────────────────────────────────────────────────

async def _verify_sse_auth(scope, receive, send):
    """ASGI middleware that validates Stytch session tokens for SSE connections.

    For stdio mode, no auth is applied (localhost only).
    """
    # Let the request pass through — we check auth on first SSE message
    pass


def _get_sse_app():
    """Return the ASGI app for SSE transport with auth middleware."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    # We use FastMCP's SSE app and wrap it with auth middleware
    raw_app = mcp.sse_app()

    class AuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            # Check auth
            auth_header = request.headers.get("Authorization", "")
            api_key = request.headers.get("x-api-key", "")

            user = None
            if auth_header.startswith("Bearer "):
                jwt = auth_header[7:]
                user = await validate_stytch_session(jwt)

            if not user and api_key:
                user = await resolve_api_token(api_key)

            # Dev mode: no Stytch configured
            if not user:
                if not settings.stytch_project_id or not settings.stytch_secret:
                    user = {"user_id": "anonymous", "email": None, "name": "Developer"}

            if not user:
                return JSONResponse(
                    {"error": "Authentication required. Set Authorization: Bearer *** or x-api-key header."},
                    status_code=401,
                )

            global _current_context
            _current_context = MCPContext(
                user_id=user["user_id"],
                email=user.get("email"),
                name=user.get("name"),
            )
            response = await call_next(request)
            return response

    auth_app = Starlette(
        routes=[
            Route("/{path:path}", endpoint=raw_app, methods=["GET"]),
        ],
        middleware=[Middleware(AuthMiddleware)],
    )
    return auth_app


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Historiador MCP Server")
    parser.add_argument("--sse", action="store_true", help="Run in SSE mode")
    parser.add_argument("--port", type=int, default=8081, help="SSE port")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="SSE host")
    args, _ = parser.parse_known_args()

    # Initialize DB
    asyncio.run(init_db())

    if args.sse:
        print(f"Starting Historiador MCP Server (SSE) on {args.host}:{args.port}")
        import uvicorn
        app = _get_sse_app()
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    else:
        print("Starting Historiador MCP Server (stdio)", file=sys.stderr)
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()