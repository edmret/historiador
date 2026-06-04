# Historiador — Multi-Agent History Generator

Generate rich, researched histories using a team of specialized AI agents.

## Architecture

```
User → Scoping Agent → Research Agents × N → Compiler → Writer → Editor → Kanban Board
                                  ↓
                          Web Crawler (search + scrape)
```

### Agent Pipeline

1. **Scoping Agent** — Interactive Q&A to refine the topic, extract subtopics, and define scope
2. **Research Agents** — Parallel web research agents that search and scrape relevant sources
3. **Compiler Agent** — Synthesizes research into structured outlines
4. **Writer Agent** — Produces markdown histories with configurable tone/length/audience
5. **Editor Agent** — Reviews quality and incorporates feedback for refinement
6. **Orchestrator** — Coordinates the full pipeline and persists state to SQLite

### Frontend

- **PWA** (Progressive Web App) — installable, works offline with cached assets
- **Hash-based Router** — no build step, vanilla JS
- **Kanban Board** — visualize history status (In Review, Refining, Accepted, Rejected)
- **Scoping Chat** — interactive refinement with the scoping agent
- **History Viewer** — full markdown rendering with feedback controls
- **Profile Manager** — create/select writing profiles (tone, audience, length)
- **Web Push Notifications** — alerts when histories are ready

## Quick Start

```bash
# Install dependencies and start (full command)
make install
make setup       # interactive wizard on first run
make start

# Or in one line (skips setup if .env already exists):
make install && make start
```

Open http://localhost:8080 in your browser.

### Available Make Targets

| Target | Description |
|--------|-------------|
| `make install` | Install Python dependencies via `uv sync` |
| `make setup`   | Run the interactive setup wizard |
| `make start`   | Start the server (auto-runs setup if `.env` missing) |
| `make dev`     | Start with hot reload (no auto-setup) |
| `make test`    | Run the test suite |
| `make lint`    | Syntax-check all Python files |
| `make migrate` | Create/seed the database (no server needed) |
| `make clean`   | Remove caches and `.db` files |

## Authentication (Stytch)

Historiador uses [Stytch](https://stytch.com) for passwordless authentication. Users log in via magic links sent to their email — no passwords to manage.

### Setup

1. **Create a Stytch account** at https://stytch.com → sign up for free
2. **Get your credentials** from the Stytch Dashboard:
   - Go to **API Keys** → copy your **Project ID** and **Secret**
   - Go to **SDK Configuration** → copy your **Public Token**
3. **Update `.env`**:

```bash
STYTCH_PROJECT_ID=proj_*
STYTCH_SECRET=***
STYTCH_PUBLIC_TOKEN=pub_*
STYTCH_ENVIRONMENT=test
```

4. **Configure email** in Stytch Dashboard → **Email** → **SMTP Settings** → set up your sender domain (or use Stytch's test domain for development)
5. **Restart** the server: `make start`

After setup, the frontend will show a login page with a Stytch magic link form. Users enter their email, receive a magic link, and are authenticated automatically.

### API Tokens (Programmatic Access)

For scripts, automation, or MCP clients, generate long-lived API tokens:

1. From the UI: navigate to **Settings** → **API Tokens**
2. Or via the API: `POST /api/auth/tokens` with `{"label": "my-token"}`
3. Use the returned token with `x-api-key: ht_...` header

API tokens never expire unless revoked. They have the same permissions as the user who created them.

## Model Context Protocol (MCP)

Historiador includes a built-in MCP server that exposes all UI operations as tools. Connect any MCP-compatible client (like Hermes Agent) to programmatically generate histories, manage topics, and configure the system.

### MCP Server

The MCP server runs on port **8081** (configurable via `MCP_PORT` in `.env`) and is enabled by default (`MCP_ENABLED=true`).

**Two transport modes:**

| Mode | Usage | Auth |
|------|-------|------|
| **SSE** (default) | `python3 backend/mcp_server.py --sse` | Requires `Authorization: Bearer ***` or `x-api-key: ht_...` |
| **stdio** | `python3 backend/mcp_server.py` | No auth (localhost only) |

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `create_topic(title)` | Create a new history topic |
| `list_topics()` | List all topics |
| `get_topic(topic_id)` | Get topic with subtopics |
| `send_scoping_message(topic_id, message)` | Send a scoping message (type "done" to end) |
| `get_scoping_messages(topic_id)` | Get scoping conversation history |
| `update_subtopic(topic_id, subtopic_id, status)` | Update subtopic status |
| `run_pipeline(topic_id, num_histories?, num_research_agents?)` | Run the full generation pipeline |
| `get_pipeline_status(topic_id)` | Get pipeline progress |
| `list_histories(topic_id?, status?)` | List histories with optional filters |
| `get_history(history_id)` | Get full history content |
| `submit_feedback(history_id, feedback_type, feedback_text?)` | Submit accept/reject/refine feedback |
| `list_profiles()` | List writing profiles |
| `create_profile(name, tone?, audience?, length?, style_notes?)` | Create a writing profile |
| `update_profile(profile_id, ...)` | Update a writing profile |
| `get_config()` | Get application configuration (masked) |
| `update_config(**kwargs)` | Update application configuration |
| `test_llm(base_url, api_key, model)` | Test LLM connection |
| `create_api_token_tool(label)` | Generate a new API token |
| `list_api_tokens_tool()` | List API tokens |
| `revoke_api_token_tool(token_id)` | Revoke an API token |
| `get_agent_config(agent_type)` | Get LLM config for a specific agent |
| `health()` | Check server health |

### Connecting Hermes to Historiador MCP

To connect your Hermes Agent to Historiador's MCP server:

1. **Start the MCP server**: `python3 backend/mcp_server.py --sse`
2. **Get an API token** from the Historiador UI (Settings → API Tokens) or via `POST /api/auth/tokens`
3. **Configure Hermes** with the MCP connection:

```yaml
# In your MCP client config:
servers:
  historiador:
    transport: sse
    url: http://localhost:8081
    headers:
      Authorization: "Bearer <your-session-token>"
      # OR use an API token:
      # x-api-key: "ht_<your-token>"
```

### Example: Generate a History via MCP

Once connected, you can use tools like:

```python
# Create a topic
create_topic(title="The Fall of the Roman Empire")

# Start scoping
send_scoping_message(topic_id=1, message="I want to focus on the economic causes")

# Run the pipeline
run_pipeline(topic_id=1, num_histories=2)

# Get results
list_histories(topic_id=1)
get_history(history_id=1)
```

### Connecting to Other MCP Clients

Any MCP-compatible client can connect to Historiador. For **stdio mode** (no auth), use:

```bash
python3 backend/mcp_server.py
```

For **SSE mode** (remote access), use:

```bash
python3 backend/mcp_server.py --sse --port=8081
```

Then authenticate with a Bearer token or API key.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_KEY` | — | API key for the LLM provider |
| `LLM_BASE_URL` | `https://api.nan.builders/v1` | OpenAI-compatible base URL |
| `LLM_MODEL` | `deepseek-v4-flash` | Default model name (used when no per-agent override) |
| `SEARCH_PROVIDER` | `duckduckgo` | Search provider (`duckduckgo`, `direct`, `hermes`, `tavily`, `serpapi`, `mock`) |
| `TAVILY_API_KEY` | — | Tavily Search API key (only needed for `tavily` provider) |
| `SERPAPI_API_KEY` | — | SerpAPI key (only needed for `serpapi` provider) |
| `HERMES_PATH` | `hermes` | Path to the Hermes CLI binary (only needed for `hermes` provider) |
| `VAPID_PUBLIC_KEY` | — | VAPID public key for web push |
| `VAPID_PRIVATE_KEY` | — | VAPID private key for web push |
| `VAPID_CLAIM_EMAIL` | `admin@historiador.app` | Email for VAPID subscription claims |
| `DATABASE_URL` | `sqlite+aiosqlite:///./historiador.db` | SQLAlchemy database URL |
| `CORS_ORIGINS` | `*` | Comma-separated allowed CORS origins |
| `DEFAULT_NUM_HISTORIES` | `2` | Number of histories to generate per topic |
| `DEFAULT_NUM_RESEARCH_AGENTS` | `3` | Number of parallel research agents |
| `MAX_QUERIES_PER_AGENT` | `3` | Max search queries per research agent |
| `MAX_PAGES_PER_QUERY` | `3` | Max pages to scrape per query |
| `MAX_CHARS_PER_PAGE` | `10000` | Max characters to extract per page |
| `RESEARCH_TIMEOUT_SECONDS` | `60` | Per-agent research timeout |
| `MAX_SCOPING_ROUNDS` | `5` | Max Q&A rounds before scoping completes |
| `STYTCH_PROJECT_ID` | — | Stytch Project ID (for authentication) |
| `STYTCH_SECRET` | — | Stytch Secret API key |
| `STYTCH_PUBLIC_TOKEN` | — | Stytch Public Token (safe for frontend) |
| `STYTCH_ENVIRONMENT` | `test` | Stytch environment (`test` or `live`) |
| `MCP_ENABLED` | `true` | Enable the MCP server |
| `MCP_PORT` | `8081` | MCP server port |
| `MCP_HOST` | `0.0.0.0` | MCP server host |

### Per-Agent Model Selection

Each agent can use a different model. Set these in the **Settings** panel or via `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SCOPING_MODEL` | *(same as `LLM_MODEL`)* | Model for the scoping agent |
| `RESEARCH_MODEL` | *(same as `LLM_MODEL`)* | Model for research agents |
| `COMPILER_MODEL` | *(same as `LLM_MODEL`)* | Model for the compiler agent |
| `WRITER_MODEL` | *(same as `LLM_MODEL`)* | Model for the writer agent |
| `EDITOR_MODEL` | *(same as `LLM_MODEL`)* | Model for the editor agent |
| `PROFILE_MODEL` | *(same as `LLM_MODEL`)* | Model for the profile agent |

All settings are persisted in the SQLite database and can be edited live through the **Settings** tab in the UI.

### Settings Panel

The Settings tab (`#settings`) provides a UI for all configuration:

- **LLM** — Base URL, API key, global model, per-agent model dropdowns, "Test LLM" button
- **Search** — Provider selector, Tavily/SerpAPI keys, Hermes path
- **Push** — VAPID public/private keys, claim email
- **App** — All pipeline limits (num histories, agents, timeouts, research caps)

## Profiles

Writing profiles control the tone, audience, and style of generated histories:

- **Tone**: neutral, dramatic, educational, humorous, epic
- **Audience**: general, academic, young, expert
- **Length**: short (~300w), medium (~800w), long (~1500w)
- **Style Notes**: custom style preferences

Profiles learn from feedback over time via the feedback records stored in SQLite.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/topics` | List all topics |
| POST | `/api/topics` | Create a new topic |
| GET | `/api/topics/{id}` | Get topic with subtopics |
| POST | `/api/topics/{id}/scoping` | Send scoping message |
| GET | `/api/topics/{id}/scoping` | Get scoping conversation |
| PATCH | `/api/topics/{id}/subtopics/{sid}` | Update subtopic status |
| GET | `/api/profiles` | List profiles |
| POST | `/api/profiles` | Create profile |
| PATCH | `/api/profiles/{id}` | Update profile |
| GET | `/api/histories` | List histories (filter by `topic_id`, `status`) |
| GET | `/api/histories/{id}` | Get full history content |
| POST | `/api/histories/{id}/feedback` | Submit feedback (accept/reject/refine) |
| POST | `/api/pipeline/run` | Run the full generation pipeline |
| GET | `/api/pipeline/status/{id}` | Get pipeline progress |
| POST | `/api/notifications/subscribe` | Subscribe to push notifications |
| GET | `/api/config` | Get all configuration (API keys masked) |
| PUT | `/api/config` | Update configuration (partial) |
| POST | `/api/config/test-llm` | Test LLM connection |
| **Auth** | | |
| GET | `/api/auth/config` | Get Stytch config (public, no auth) |
| POST | `/api/auth/login` | Exchange session JWT for user info |
| GET | `/api/auth/me` | Get current user (Bearer JWT or x-api-key) |
| POST | `/api/auth/tokens` | Create API token (requires auth) |
| GET | `/api/auth/tokens` | List API tokens (requires auth) |
| DELETE | `/api/auth/tokens/{id}` | Revoke API token (requires auth) |

## Tech Stack

- **Backend**: Python 3.13, FastAPI, SQLAlchemy 2.0 (async), SQLite, aiohttp, httpx
- **Frontend**: Vanilla JS, CSS custom properties, PWA (service worker + manifest)
- **LLM**: OpenAI-compatible API (any provider)
- **Search**: DuckDuckGo (free, default), Direct DuckDuckGo scraping, Hermes CLI subagent, Tavily, or SerpAPI
- **Auth**: Stytch (passwordless magic links + API tokens)
- **MCP**: Model Context Protocol (stdio + SSE transports)

## Deployment

### Docker Compose (Recommended)

```bash
# 1. Clone and configure
git clone git@github.com:edmret/historiador.git
cd historiador
cp .env.example .env
# Edit .env with your LLM_API_KEY and other settings

# 2. Build and start
docker compose up --build -d

# 3. Open
# Web UI:   http://localhost:8080
# MCP SSE:  http://localhost:8081
```

This starts two containers:
- **historiador** — FastAPI server + static frontend on `:8080`
- **mcp** — MCP server on `:8081`

Both share a Docker volume (`historian-data`) for the SQLite database, so data persists across restarts.

### Environment Variables

Set these in `.env` before deploying (or pass via `docker compose run -e`):

| Variable | Required | Note |
|----------|----------|------|
| `LLM_API_KEY` | ✅ | Your LLM provider API key |
| `LLM_BASE_URL` | ✅ | OpenAI-compatible base URL |
| `LLM_MODEL` | — | Default: `deepseek-v4-flash` |
| `DATABASE_URL` | — | Auto‑configured to use the persisted volume |
| `STYTCH_PROJECT_ID` | — | Optional: enable auth |
| `STYTCH_SECRET` | — | Optional: enable auth |
| `STYTCH_PUBLIC_TOKEN` | — | Optional: enable auth |

All other settings (search provider, VAPID keys, per‑agent models, pipeline limits) can be edited live in the **Settings** panel after first run.

### Health Checks

Both containers include Docker health checks. Check status with:

```bash
docker compose ps
docker compose logs historian
docker compose logs mcp
```

### Updating

```bash
docker compose down
git pull
docker compose up --build -d
```

## Project Structure

```
historiador/
├── backend/
│   ├── agents/          # AI agents (scoping, research, compiler, writer, editor, orchestrator)
│   ├── auth/            # Stytch auth + API token management
│   ├── crawler/         # Web search and scraping
│   ├── models/          # SQLAlchemy ORM models
│   ├── schemas/         # Pydantic request/response schemas
│   ├── routers/         # FastAPI route handlers
│   ├── services/        # Business logic (AppConfigService)
│   ├── notifications/   # Web Push notifications
│   ├── migrations/      # DB migration scripts
│   ├── config.py        # Application settings
│   ├── database.py      # DB engine and session factory
│   ├── llm_client.py    # OpenAI-compatible LLM client
│   ├── mcp_server.py    # MCP server (stdio + SSE)
│   └── main.py          # FastAPI application entry point
├── frontend/
│   ├── css/             # Stylesheets
│   ├── js/              # JavaScript modules (router, components, API client, settings)
│   ├── assets/          # Icons and static assets
│   ├── index.html       # Main HTML entry point
│   ├── manifest.json    # PWA manifest
│   └── service-worker.js# PWA service worker
├── scripts/
│   └── run.sh           # Server startup script
├── Dockerfile           # Production Docker image
├── Dockerfile.mcp       # MCP server Docker image
├── docker-compose.yml   # Multi-service deployment
├── .dockerignore        # Docker build exclusions
├── pyproject.toml       # Python dependencies
├── .env.example         # Environment template
└── README.md
```