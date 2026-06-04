"""Configuration API router for Historiador."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from backend.services.app_config_service import get_app_config_service

router = APIRouter(prefix="/api/config", tags=["config"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ConfigUpdate(BaseModel):
    """Partial config update — only provided fields are changed."""

    llm_api_key: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_model: Optional[str] = None
    scoping_model: Optional[str] = None
    research_model: Optional[str] = None
    compiler_model: Optional[str] = None
    writer_model: Optional[str] = None
    editor_model: Optional[str] = None
    profile_model: Optional[str] = None
    search_provider: Optional[str] = None
    tavily_api_key: Optional[str] = None
    serpapi_api_key: Optional[str] = None
    hermes_path: Optional[str] = None
    vapid_public_key: Optional[str] = None
    vapid_private_key: Optional[str] = None
    vapid_claim_email: Optional[str] = None
    database_url: Optional[str] = None
    cors_origins: Optional[str] = None
    default_num_histories: Optional[int] = None
    default_num_research_agents: Optional[int] = None
    max_scoping_rounds: Optional[int] = None
    max_queries_per_agent: Optional[int] = None
    max_pages_per_query: Optional[int] = None
    max_chars_per_page: Optional[int] = None
    max_research_tokens: Optional[int] = None
    research_timeout_seconds: Optional[int] = None


class LLMTestRequest(BaseModel):
    base_url: str
    api_key: str
    model: str


class LLMTestResponse(BaseModel):
    success: bool
    message: str


class ConfigResponse(BaseModel):
    """Config with API keys masked."""

    data: dict
    masked_keys: list[str] = [
        "llm_api_key",
        "tavily_api_key",
        "serpapi_api_key",
        "vapid_private_key",
    ]

    def model_post_init(self, __context):
        for key in self.masked_keys:
            if key in self.data and self.data[key]:
                val = self.data[key]
                if len(val) > 4:
                    self.data[key] = val[:4] + "..." + val[-4:]
                else:
                    self.data[key] = "****"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=ConfigResponse)
async def get_config():
    """Return all configuration (API keys masked)."""
    svc = get_app_config_service()
    config = await svc.get_config()
    return ConfigResponse(data=config)


@router.put("", response_model=ConfigResponse)
async def update_config(body: ConfigUpdate):
    """Update configuration. Only provided fields are changed."""
    svc = get_app_config_service()
    # Filter out None values
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    if not data:
        config = await svc.get_config()
        return ConfigResponse(data=config)
    updated = await svc.update_config(data)
    return ConfigResponse(data=updated)


@router.post("/test-llm", response_model=LLMTestResponse)
async def test_llm(body: LLMTestRequest):
    """Test LLM connection with given credentials."""
    svc = get_app_config_service()
    success, message = await svc.test_llm_connection(
        body.base_url, body.api_key, body.model
    )
    return LLMTestResponse(success=success, message=message)
