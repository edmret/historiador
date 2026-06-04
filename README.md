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
# 1. Install dependencies
uv sync

# 2. Run the setup wizard (interactive)
uv run python scripts/setup.py

# Or use quick mode and edit .env manually:
# uv run python scripts/setup.py --quick

# 3. Start the server
bash scripts/run.sh
# Or directly: uvicorn backend.main:app --reload
```

Open http://localhost:8080 in your browser.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_KEY` | — | API key for the LLM provider |
| `LLM_BASE_URL` | `https://api.nan.builders/v1` | OpenAI-compatible base URL |
| `LLM_MODEL` | `deepseek-v4-flash` | Model name |
|| `SEARCH_PROVIDER` | `duckduckgo` | Search provider (`duckduckgo`, `direct`, `hermes`, `tavily`, `serpapi`, `mock`) |
|| `TAVILY_API_KEY` | — | Tavily Search API key (only needed for `tavily` provider) |
|| `SERPAPI_API_KEY` | — | SerpAPI key (only needed for `serpapi` provider) |
|| `HERMES_PATH` | `hermes` | Path to the Hermes CLI binary (only needed for `hermes` provider) |
| `DEFAULT_NUM_HISTORIES` | `2` | Number of histories to generate per topic |
| `DEFAULT_NUM_RESEARCH_AGENTS` | `3` | Number of parallel research agents |
| `MAX_QUERIES_PER_AGENT` | `3` | Max search queries per research agent |
| `MAX_PAGES_PER_QUERY` | `3` | Max pages to scrape per query |
| `MAX_CHARS_PER_PAGE` | `10000` | Max characters to extract per page |
| `RESEARCH_TIMEOUT_SECONDS` | `60` | Per-agent research timeout |
| `MAX_SCOPING_ROUNDS` | `5` | Max Q&A rounds before scoping completes |

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

## Tech Stack

- **Backend**: Python 3.13, FastAPI, SQLAlchemy 2.0 (async), SQLite, aiohttp, httpx
- **Frontend**: Vanilla JS, CSS custom properties, PWA (service worker + manifest)
- **LLM**: OpenAI-compatible API (any provider)
- **Search**: DuckDuckGo (free, default), Direct DuckDuckGo scraping, Hermes CLI subagent, Tavily, or SerpAPI

## Project Structure

```
historiador/
├── backend/
│   ├── agents/          # AI agents (scoping, research, compiler, writer, editor, orchestrator)
│   ├── crawler/         # Web search and scraping
│   ├── models/          # SQLAlchemy ORM models
│   ├── schemas/         # Pydantic request/response schemas
│   ├── routers/         # FastAPI route handlers
│   ├── notifications/   # Web Push notifications
│   ├── migrations/      # DB migration scripts
│   ├── config.py        # Application settings
│   ├── database.py      # DB engine and session factory
│   ├── llm_client.py    # OpenAI-compatible LLM client
│   └── main.py          # FastAPI application entry point
├── frontend/
│   ├── css/             # Stylesheets
│   ├── js/              # JavaScript modules (router, components, API client)
│   ├── assets/          # Icons and static assets
│   ├── index.html       # Main HTML entry point
│   ├── manifest.json    # PWA manifest
│   └── service-worker.js# PWA service worker
├── scripts/
│   └── run.sh           # Server startup script
├── pyproject.toml       # Python dependencies
├── .env.example         # Environment template
└── README.md
```