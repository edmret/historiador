# Historiador — Multi-Agent History Generation System

> **For Hermes:** Implement this plan task-by-task using subagent-driven-development.

**Goal:** Build a multi-agent application where a user submits a topic, multiple research agents crawl the web, a writer agent creates markdown histories, and a PWA with Kanban board handles approval/refinement workflow — output formatted for YouTube videos.

**Architecture:** FastAPI backend with a custom async agent orchestration layer (no LangChain — simpler, more maintainable). SQLite for persistence. PWA frontend with service worker push notifications. All agents use the OpenAI-compatible API via the custom provider.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy + SQLite, aiohttp (web crawling), PWA (HTML/CSS/JS, Service Worker, Web Push), GitHub for delivery.

---

## Architecture Overview

```
┌─────────────┐     ┌─────────────────────────────────────┐     ┌──────────┐
│   User      │────▶│        FastAPI Backend               │────▶│  SQLite  │
│  (PWA/API)  │◀────│                                     │◀────│   DB     │
└─────────────┘     │  ┌───────────────────────────────┐  │     └──────────┘
                    │  │   Agent Orchestrator            │  │
                    │  │  ┌────────┐ ┌────────┐ ┌─────┐ │  │
                    │  │  │Research│ │Research│ │ ... │ │  │
                    │  │  │Agent 1 │ │Agent 2 │ │     │ │  │
                    │  │  └────┬───┘ └────┬───┘ └──┬──┘ │  │
                    │  │       │           │        │     │  │
                    │  │       ▼           ▼        ▼     │  │
                    │  │  ┌─────────────────────────┐     │  │
                    │  │  │    Compiler Agent         │     │  │
                    │  │  └───────────┬─────────────┘     │  │
                    │  │              ▼                    │  │
                    │  │  ┌─────────────────────────┐     │  │
                    │  │  │    Writer Agent           │     │  │
                    │  │  │  (creates N histories)   │     │  │
                    │  │  └───────────┬─────────────┘     │  │
                    │  │              ▼                    │  │
                    │  │  ┌─────────────────────────┐     │  │
                    │  │  │    Editor Agent           │     │  │
                    │  │  │  (refines on feedback)   │     │  │
                    │  │  └─────────────────────────┘     │  │
                    │  └───────────────────────────────┘  │  │
                    │                                      │  │
                    │  ┌───────────────────────────────┐  │  │
                    │  │   Web Push Notification        │  │  │
                    │  └───────────────────────────────┘  │  │
                    └─────────────────────────────────────┘  │
                                      │                      │
                                      ▼                      ▼
                    ┌──────────────────────────────────────────┐
                    │        PWA Frontend                       │
                    │  - Kanban Board                           │
                    │  - History Viewer & Editor                │
                    │  - Service Worker + Push Notifications    │
                    └──────────────────────────────────────────┘
```

### Agent Flow

```
User submits topic "The French Revolution"
  │
  ▼
[Orchestrator] creates topic record (status: researching)
  │
  ├── [Research Agent 1] "Historical Context"  ──▶ Crawls web for background
  ├── [Research Agent 2] "Key Figures"          ──▶ Crawls web for people/perspectives
  ├── [Research Agent 3] "Impact & Legacy"      ──▶ Crawls web for consequences
  │         (N agents, configurable)
  │
  ▼
[Orchestrator] updates topic (status: compiled)
  │
  ▼
[Compiler Agent] Deduplicates & merges all research → comprehensive context
  │
  ▼
[Orchestrator] updates topic (status: writing)
  │
  ▼
[Writer Agent] Creates N histories (default: 2) in markdown + push notification
  │
  ▼
[Orchestrator] updates topic (status: histories_created)
              histories status: in_review
  │
  ▼
User sees on Kanban board → clicks on history to read
  │
  ├── Accept → status: accepted ✅  (ready for YouTube video)
  ├── Reject → status: rejected ❌
  ├── Refine → status: refining  ⟳  (Editor Agent runs with feedback)
  │          └── Editor Agent refines → status: in_review again
  └── Iterate → edit requests loop through Editor Agent
```

### YouTube Format

Histories are markdown with sections designed for scriptwriting:
- `## Title` — video title
- `## Hook` — opening hook (first 15 seconds)
- `## Narrative` — main body as sections
- `## Key Visuals` — suggested visuals/B-roll descriptions
- `## Call to Action` — ending

---

### Research Guardrails (Anti-Infinite Loop)

Every research agent has hard limits that prevent unbounded crawling:

| Limit | Default | Config Key | What it prevents |
|-------|---------|------------|-----------------|
| Max search queries per agent | 3 | `max_queries_per_agent` | Agent can't generate endless search terms |
| Max pages scraped per query | 3 | `max_pages_per_query` | Agent doesn't crawl every link |
| Max content length per page | 10,000 chars | `max_chars_per_page` | Agent doesn't read entire books |
| Max total tokens per research phase | 8,000 | `max_research_tokens` | LLM synthesis has a budget |
| Timeout per agent | 60 seconds | `research_timeout_seconds` | Whole agent run timed out at OS/HTTP level |
| Max total pages per topic | 27 | `max_total_pages` | = queries × pages × agents (3×3×3) |

**In code:** The research agent uses `asyncio.wait_for()` with the timeout, slices page content to `max_chars_per_page`, limits its search query generation to `max_queries_per_agent`, and the orchestrator cancels any agent that exceeds its budget. No infinite loops, no runaway costs.

---

## File Structure

```
historiador/
├── pyproject.toml              # Python deps (uv)
├── .env.example                # Config template
├── README.md
│
├── backend/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry, lifespan, CORS
│   ├── config.py               # Settings from env vars
│   ├── database.py             # SQLAlchemy engine, session factory
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── topic.py            # Topic model
│   │   ├── history.py          # History model
│   │   └── research_source.py  # ResearchSource model
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── topic.py            # Pydantic schemas for topics
│   │   ├── history.py          # Pydantic schemas for histories
│   │   └── kanban.py           # Pydantic schemas for kanban state
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── topics.py           # /api/topics endpoints
│   │   ├── histories.py        # /api/histories endpoints
│   │   ├── kanban.py           # /api/kanban endpoints
│   │   └── notifications.py    # /api/push-subscription endpoints
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── orchestrator.py     # Main orchestrator: manages entire flow
│   │   ├── research_agent.py   # Web crawling + research
│   │   ├── compiler.py         # Merges & deduplicates research
│   │   ├── writer.py           # Creates histories from compiled research
│   │   ├── editor.py           # Refines histories from user feedback
│   │   └── llm_client.py       # Shared OpenAI-compatible client
│   │
│   ├── crawler/
│   │   ├── __init__.py
│   │   ├── search.py           # Web search abstraction (Tavily/SerpAPI/fallback)
│   │   └── scraper.py          # Web page content extraction
│   │
│   ├── notifications/
│   │   ├── __init__.py
│   │   └── push.py             # Web push notification sender
│   │
│   └── migrations/
│       └── init_db.py          # Create tables
│
├── frontend/
│   ├── index.html              # SPA entry point
│   ├── manifest.json           # PWA manifest
│   ├── service-worker.js       # Push notifications + offline cache
│   ├── css/
│   │   └── app.css             # Styles (kanban, cards, responsive)
│   ├── js/
│   │   ├── app.js              # Main app: routing, state
│   │   ├── api.js              # API client
│   │   ├── kanban.js           # Kanban board rendering
│   │   ├── history-viewer.js   # Markdown rendering + approve/reject UI
│   │   └── notifications.js    # Push subscription management
│   └── assets/
│       ├── icons/              # PWA icons
│       └── logo.svg
│
└── scripts/
    └── run.sh                  # Run backend + serve frontend
```

---

## Database Schema

```sql
-- Topics table
CREATE TABLE topics (
    id TEXT PRIMARY KEY,          -- UUID
    title TEXT NOT NULL,          -- User's topic
    status TEXT NOT NULL DEFAULT 'pending',
        -- pending → researching → compiled → writing → histories_created
    num_histories INTEGER NOT NULL DEFAULT 2,  -- How many histories to generate
    num_research_agents INTEGER NOT NULL DEFAULT 3,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Histories table
CREATE TABLE histories (
    id TEXT PRIMARY KEY,          -- UUID
    topic_id TEXT NOT NULL REFERENCES topics(id),
    title TEXT NOT NULL,          -- History title
    content TEXT NOT NULL,        -- Full markdown content
    status TEXT NOT NULL DEFAULT 'in_review',
        -- in_review → refining → accepted | rejected
    feedback TEXT,                -- Last editor feedback (if refining)
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Research sources table
CREATE TABLE research_sources (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id),
    agent_name TEXT NOT NULL,     -- Which research agent found this
    url TEXT NOT NULL,
    title TEXT,
    content_snippet TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Push subscriptions table
CREATE TABLE push_subscriptions (
    id TEXT PRIMARY KEY,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/topics` | Create topic → triggers agent flow |
| GET | `/api/topics` | List all topics with status |
| GET | `/api/topics/{id}` | Topic details + histories |
| GET | `/api/kanban` | Kanban board state (grouped by status) |
| GET | `/api/histories` | List histories (query param: status) |
| GET | `/api/histories/{id}` | Get single history markdown |
| PATCH | `/api/histories/{id}` | Update status (approve/reject) |
| POST | `/api/histories/{id}/refine` | Send refinement feedback → Editor Agent |
| POST | `/api/push-subscribe` | Register push subscription |
| GET | `/api/push-public-key` | Get VAPID public key |
| GET | `/api/health` | Health check |
| GET | `/api/topics/{id}/logs` | Get processing logs for a topic |

---

## Dependency Map

```
BATCH 1 (parallel — independent files):
  Task 1:  Create pyproject.toml + config
  Task 2:  Create database models + schema
  Task 3:  Create PWA manifest + service-worker.js

BATCH 2 (depends on Batch 1):
  Task 4:  Create database.py + migrations (depends on Task 1, 2)
  Task 5:  Create API schemas (depends on Task 2)

BATCH 3 (depends on Batch 2):
  Task 6:  Create LLM client (depends on Task 1)
  Task 7:  Create crawler/search/scraper (depends on Task 1)
  Task 8:  Create push notification module (depends on Task 1)

BATCH 4 (depends on Batch 3):
  Task 9:  Create Research Agent (depends on Task 6, 7)
  Task 10: Create Compiler Agent (depends on Task 6)
  Task 11: Create Writer Agent (depends on Task 6)

BATCH 5 (depends on Batch 4):
  Task 12: Create Editor Agent (depends on Task 6)
  Task 13: Create Orchestrator (depends on Task 9, 10, 11, 12)

BATCH 6 (depends on Batch 2, 5):
  Task 14: Create API routers - topics + histories (depends on Task 4, 5, 13)
  Task 15: Create API routers - kanban + notifications (depends on Task 4, 5, 8)

BATCH 7 (depends on Batch 6):
  Task 16: Create FastAPI main.py (depends on Task 14, 15)

BATCH 8 (parallel — independent files):
  Task 17: Create frontend CSS
  Task 18: Create frontend JS - API client + notifications
  Task 19: Create frontend HTML structure

BATCH 9 (depends on Batch 8):
  Task 20: Create kanban.js board rendering
  Task 21: Create history-viewer.js

BATCH 10 (depends on Batch 9):
  Task 22: Wire up app.js (depends on 18, 20, 21)

BATCH 11:
  Task 23: Create README.md + .env.example + run.sh
  Task 24: End-to-end test
```

---

## Detailed Tasks

### Task 1: Create pyproject.toml and config

**Objective:** Set up Python project with uv, dependencies, and config module

**Files:**
- Create: `pyproject.toml`
- Create: `backend/__init__.py`
- Create: `backend/config.py`

**pyproject.toml:**
```toml
[project]
name = "historiador"
version = "0.1.0"
description = "Multi-agent history generation system"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "sqlalchemy>=2.0.0",
    "aiosqlite>=0.20.0",
    "httpx>=0.28.0",
    "aiohttp>=3.10.0",
    "beautifulsoup4>=4.12.0",
    "lxml>=5.3.0",
    "pywebpush>=1.14.0",
    "cryptography>=43.0.0",
    "python-dotenv>=1.0.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
]
```

**config.py:**
```python
from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.nan.builders/v1"
    llm_model: str = "deepseek-v4-flash"

    # Web Search
    search_provider: str = "tavily"  # tavily, serpapi, or "duckduckgo"
    tavily_api_key: str = ""
    serpapi_api_key: str = ""

    # Web Push (VAPID)
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_claim_email: str = "admin@historiador.app"

    # App
    database_url: str = "sqlite+aiosqlite:///./historiador.db"
    cors_origins: str = "*"
    default_num_histories: int = 2
    default_num_research_agents: int = 3

    # Research Guardrails
    max_queries_per_agent: int = 3
    max_pages_per_query: int = 3
    max_chars_per_page: int = 10_000
    max_research_tokens: int = 8_000
    research_timeout_seconds: int = 60

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

settings = Settings()
```

---

### Task 2: Create database models

**Objective:** Define SQLAlchemy ORM models for topics, histories, research_sources, push_subscriptions

**Files:**
- Create: `backend/models/__init__.py`
- Create: `backend/models/topic.py`
- Create: `backend/models/history.py`
- Create: `backend/models/research_source.py`

**topic.py:**
```python
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class Topic(Base):
    __tablename__ = "topics"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    status = Column(String, default="pending")
    num_histories = Column(Integer, default=2)
    num_research_agents = Column(Integer, default=3)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

Similarly for History, ResearchSource, and PushSubscription models.

---

### Task 3: Create PWA manifest + service-worker.js

**Objective:** Create PWA foundation files

**Files:**
- Create: `frontend/manifest.json`
- Create: `frontend/service-worker.js`

**manifest.json:**
```json
{
  "name": "Historiador",
  "short_name": "Historiador",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#1a1a2e",
  "theme_color": "#0f3460",
  "icons": [...]
}
```

**service-worker.js:** Cache static assets, handle push events, show notifications on click.

---

### Task 4: Create database.py + migrations

**Objective:** Set up SQLAlchemy engine, session factory, and table creation

**Files:**
- Create: `backend/database.py`
- Create: `backend/migrations/__init__.py`
- Create: `backend/migrations/init_db.py`

**database.py:**
```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from backend.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def get_db():
    async with async_session() as session:
        yield session
```

---

### Task 5: Create API Pydantic schemas

**Objective:** Define request/response schemas for all API endpoints

**Files:**
- Create: `backend/schemas/__init__.py`
- Create: `backend/schemas/topic.py`
- Create: `backend/schemas/history.py`
- Create: `backend/schemas/kanban.py`

**topic.py example:**
```python
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

class TopicCreate(BaseModel):
    title: str
    num_histories: int = 2
    num_research_agents: int = 3

class TopicResponse(BaseModel):
    id: str
    title: str
    status: str
    num_histories: int
    num_research_agents: int
    created_at: datetime
    updated_at: datetime

class TopicDetail(TopicResponse):
    histories: List["HistorySummary"] = []
```

---

### Task 6: Create LLM client

**Objective:** Shared client for calling OpenAI-compatible API

**Files:**
- Create: `backend/agents/__init__.py`
- Create: `backend/agents/llm_client.py`

**llm_client.py:**
```python
import httpx
from backend.config import settings

class LLMClient:
    def __init__(self):
        self.base_url = settings.llm_base_url
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model

    async def chat(self, messages: list, temperature: float = 0.7) -> str:
        """Send a chat completion request and return the response text."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                },
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
```

---

### Task 7: Create crawler/search/scraper

**Objective:** Web search and content extraction utilities

**Files:**
- Create: `backend/crawler/__init__.py`
- Create: `backend/crawler/search.py`
- Create: `backend/crawler/scraper.py`

**search.py:** Abstracts web search - supports Tavily, SerpAPI, and DuckDuckGo fallback
**scraper.py:** Fetches and extracts text from web pages using aiohttp + BeautifulSoup

---

### Task 8: Create push notification module

**Objective:** Send web push notifications when histories are created

**Files:**
- Create: `backend/notifications/__init__.py`
- Create: `backend/notifications/push.py`

**push.py:** Uses pywebpush to send notifications to subscribed browsers.

---

### Task 9: Create Research Agent

**Objective:** Agent that researches a topic from a specific angle, bounded by hard limits

**Files:**
- Modify: `backend/agents/__init__.py`
- Create: `backend/agents/research_agent.py`

```python
class ResearchAgent:
    """Researches a topic from a specific perspective.
    
    BOUNDED by:
    - max_queries_per_agent: stops generating search terms after N
    - max_pages_per_query: only scrapes top N results per query
    - max_chars_per_page: truncates page content to N chars
    - research_timeout_seconds: asyncio.wait_for kills the whole agent
    """

    def __init__(self, perspective: str, llm: LLMClient, settings: Settings):
        self.perspective = perspective
        self.llm = llm
        self.settings = settings

    async def research(self, topic: str) -> ResearchResult:
        """1. Generate search queries (capped by max_queries_per_agent)
           2. Search web for each query (capped by max_pages_per_query)
           3. Scrape top results (truncated by max_chars_per_page)
           4. Use LLM to synthesize findings (capped by max_research_tokens)
           
           Entire method wrapped in asyncio.wait_for(timeout=research_timeout_seconds)
        """
```

**Key implementation details:**
- `asyncio.wait_for()` wraps the entire `research()` method with `research_timeout_seconds`
- Search query generation prompt says "Generate at most {max_queries_per_agent} search queries"
- Page content sliced to `content[:max_chars_per_page]`
- Scraper fetches at most `max_pages_per_query` URLs per query
- Any `asyncio.TimeoutError` is caught gracefully — the agent returns whatever it found so far

---

### Task 10: Create Compiler Agent

**Objective:** Merge all research agents' output into comprehensive context

**Files:**
- Create: `backend/agents/compiler.py`

```python
class CompilerAgent:
    """Takes all research outputs and compiles into structured context."""

    async def compile(self, research_results: list[ResearchResult]) -> str:
        """Deduplicate, organize by theme, produce comprehensive markdown context."""
```

---

### Task 11: Create Writer Agent

**Objective:** Create N markdown histories from compiled research

**Files:**
- Create: `backend/agents/writer.py`

```python
class WriterAgent:
    """Creates histories in YouTube-ready markdown format."""

    async def write_histories(self, compiled_context: str, n: int = 2) -> list[dict]:
        """Generate N distinct histories with proper structure."""
```

Output format:
```markdown
## Title: [Engaging Title]

## Hook
[15-second opening hook]

## Narrative
[Body with sections, storytelling flow]

## Key Visuals
[Suggested visuals for YouTube video]

## Call to Action
[Closing]
```

---

### Task 12: Create Editor Agent

**Objective:** Refine a history based on user feedback

**Files:**
- Create: `backend/agents/editor.py`

```python
class EditorAgent:
    """Refines a history given user feedback."""

    async def refine(self, history_content: str, feedback: str) -> str:
        """Apply feedback and return improved markdown."""
```

---

### Task 13: Create Orchestrator

**Objective:** Coordinate the entire agent workflow in the background

**Files:**
- Create: `backend/agents/orchestrator.py`

```python
class Orchestrator:
    """Manages the full lifecycle of a topic → histories pipeline."""

    async def run(self, topic_id: str):
        """Orchestrates: research → compile → write → notify."""
```

The orchestrator runs as a background task (FastAPI BackgroundTasks or asyncio.create_task).

---

### Task 14: Create API routers - topics + histories

**Objective:** CRUD endpoints for topics and histories

**Files:**
- Create: `backend/routers/__init__.py`
- Create: `backend/routers/topics.py`
- Create: `backend/routers/histories.py`

**topics.py key endpoint:**
```python
@router.post("/topics")
async def create_topic(data: TopicCreate, background_tasks: BackgroundTasks, db=Depends(get_db)):
    """Create topic record, return immediately, kick off orchestrator in background."""
```

---

### Task 15: Create API routers - kanban + notifications

**Objective:** Kanban board state + notification subscription endpoints

**Files:**
- Create: `backend/routers/kanban.py`
- Create: `backend/routers/notifications.py`

**kanban.py:**
```python
@router.get("/kanban")
async def get_kanban(db=Depends(get_db)):
    """Return all topics+histories grouped by status for kanban rendering."""
    # Returns: { researching: [...], compiled: [...], in_review: [...], refining: [...], accepted: [...], rejected: [...] }
```

---

### Task 16: Create FastAPI main.py

**Objective:** Wire up all routers, CORS, lifespan, static file serving

**Files:**
- Create: `backend/main.py`

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from backend.database import engine
from backend.models.topic import Base
from backend.routers import topics, histories, kanban, notifications

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(title="Historiador", lifespan=lifespan)
# CORS middleware
# Mount static files for frontend
# Include routers
```

---

### Task 17: Create frontend CSS

**Objective:** Styling for PWA — dark theme, kanban board, history viewer

**Files:**
- Create: `frontend/css/app.css`

Dark theme kanban board with draggable cards. Status-colored columns.

---

### Task 18: Create frontend JS - API client + notifications

**Objective:** API wrapper and push notification registration

**Files:**
- Create: `frontend/js/api.js`
- Create: `frontend/js/notifications.js`

**api.js:** Fetch-based client, all endpoints
**notifications.js:** Service worker registration, push subscription management

---

### Task 19: Create frontend HTML structure

**Objective:** Main SPA shell with navigation

**Files:**
- Create: `frontend/index.html`

Navigation: Kanban view | Topic creation | History viewer

---

### Task 20: Create kanban.js

**Objective:** Kanban board rendering with drag-drop

**Files:**
- Create: `frontend/js/kanban.js`

Columns: Researching → Compiling → Writing → In Review → Refining → Accepted → Rejected

---

### Task 21: Create history-viewer.js

**Objective:** Markdown rendering + action buttons

**Files:**
- Create: `frontend/js/history-viewer.js`

Renders markdown, shows Approve/Reject/Refine buttons, refinement feedback modal.

---

### Task 22: Wire up app.js

**Objective:** Main app controller — routing, page switching, initial load

**Files:**
- Create: `frontend/js/app.js`

Router: hash-based (/#kanban, /#history/xxx).
Auto-refresh kanban every 10 seconds. Notification click handling.

---

### Task 23: Create README.md + .env.example + run.sh

**Objective:** Documentation and setup scripts

**Files:**
- Create: `README.md`
- Create: `.env.example`
- Create: `scripts/run.sh`

---

### Task 24: End-to-end test

**Objective:** Verify the entire system works end-to-end

**Steps:**
1. Run `uv sync`
2. Run `python -m backend.main` or `uv run uvicorn backend.main:app`
3. Create a topic via API
4. Verify research agents run, compiler runs, writer runs
5. Verify histories appear in kanban
6. Test approve/reject/refine flow
7. Run full test suite

---

## Future Considerations (Not in Scope Yet)

- YouTube API integration for direct video creation
- Multiple output formats (HTML, PDF, SRT)
- User authentication / multi-tenant
- Docker deployment
- Agent progress streaming via WebSockets
- History version history