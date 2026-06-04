from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    llm_api_key: str = ""
    llm_base_url: str = "https://api.nan.builders/v1"
    llm_model: str = "deepseek-v4-flash"
    search_provider: str = "duckduckgo"
    tavily_api_key: str = ""
    serpapi_api_key: str = ""
    hermes_path: str = "hermes"  # path/command to the hermes CLI binary
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_claim_email: str = "admin@historiador.app"
    database_url: str = "sqlite+aiosqlite:///./historiador.db"
    cors_origins: str = "*"
    default_num_histories: int = 2
    default_num_research_agents: int = 3
    max_scoping_rounds: int = 5
    max_queries_per_agent: int = 3
    max_pages_per_query: int = 3
    max_chars_per_page: int = 10000
    max_research_tokens: int = 8000
    research_timeout_seconds: int = 60

    # ── Stytch Authentication ──
    stytch_project_id: str = ""
    stytch_secret: str = ""
    stytch_public_token: str = ""
    stytch_environment: str = "live"  # "test" or "live"

    # ── MCP Server ──
    mcp_enabled: bool = True
    mcp_port: int = 8081
    mcp_host: str = "0.0.0.0"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()