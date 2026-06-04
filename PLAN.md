# Plan: Per-Agent Model Selection + UI Configuration

## Goal
1. Allow each agent type (scoping, research, compiler, writer, editor, profile) to use a different LLM model
2. Expose all configuration (LLM, search, push, app settings) through the UI
3. Persist configuration in SQLite (not just `.env`)
4. Keep `.env` as fallback/defaults

## Architecture

### 1. New DB Model: `AppConfig`
- Table storing key-value pairs for all configuration
- Keys: `llm_api_key`, `llm_base_url`, `llm_model`, `search_provider`, `tavily_api_key`, `serpapi_api_key`, `hermes_path`, `vapid_public_key`, `vapid_private_key`, `vapid_claim_email`, `default_num_histories`, `default_num_research_agents`, `max_scoping_rounds`, `max_queries_per_agent`, `max_pages_per_query`, `max_chars_per_page`, `max_research_tokens`, `research_timeout_seconds`
- Per-agent model keys: `scoping_model`, `research_model`, `compiler_model`, `writer_model`, `editor_model`, `profile_model`

### 2. New `AppConfigService`
- Singleton that reads from DB with `.env` fallback
- `get_config()` returns full config dict
- `update_config(data)` writes to DB
- `get_agent_config(agent_type)` returns {base_url, api_key, model} for that agent

### 3. Update `LLMClient`
- Accept per-client config: `LLMClient(config={"base_url": ..., "api_key": ..., "model": ...})`
- Orchestrator creates separate LLMClient instances per agent type

### 4. Update Orchestrator
- Create per-agent LLM clients during init:
  ```python
  self.scoping_llm = LLMClient(config=app_config.get_agent_config("scoping"))
  self.research_llm = LLMClient(config=app_config.get_agent_config("research"))
  self.compiler_llm = LLMClient(config=app_config.get_agent_config("compiler"))
  self.writer_llm = LLMClient(config=app_config.get_agent_config("writer"))
  self.editor_llm = LLMClient(config=app_config.get_agent_config("editor"))
  self.profile_llm = LLMClient(config=app_config.get_agent_config("profile"))
  ```

### 5. New API Router: `/api/config`
- `GET /api/config` — return all config (mask API keys)
- `PUT /api/config` — update config (write to DB)
- `POST /api/config/test-llm` — test LLM connection with given credentials
- `GET /api/config/available-models` — list available models (from config or auto-detect)

### 6. Frontend: Settings Page
- New route: `#settings`
- Tabbed interface:
  - **LLM**: base URL, API key, model selector (per-agent dropdowns)
  - **Search**: provider selector, API keys (conditional)
  - **Push**: VAPID keys (generate button), email
  - **App**: num histories, agents, limits
- "Save" button calls `PUT /api/config`
- "Test Connection" button calls `POST /api/config/test-llm`

## Implementation Order
1. DB model + service for AppConfig
2. Update LLMClient to accept per-instance config
3. Update orchestrator to use per-agent LLM clients
4. API router for config CRUD + test
5. Frontend settings page
6. Update run.sh / setup.py to seed initial config into DB

## Files to Create/Modify
- `backend/models/app_config.py` — NEW
- `backend/services/app_config_service.py` — NEW
- `backend/llm_client.py` — modify
- `backend/agents/orchestrator.py` — modify
- `backend/routers/config.py` — NEW
- `backend/main.py` — register config router
- `frontend/js/settings-page.js` — NEW
- `frontend/js/app.js` — add settings route
- `frontend/css/app.css` — add settings styles
- `frontend/index.html` — add settings tab
- `backend/migrations/run.py` — seed initial config
- `scripts/setup.py` — seed config into DB after wizard
