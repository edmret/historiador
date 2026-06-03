# Historiador — Multi-Agent History Generation System

> **For Hermes:** Implement this plan task-by-task using subagent-driven-development.

**Goal:** Build a multi-agent PWA where a user submits a topic, a scoping agent clarifies it via interactive questions, research agents crawl the web, a writer agent creates markdown histories (with configurable tone profiles), and a Kanban board handles the full approval/refinement workflow — with subtopic todo management and feedback learning.

**Architecture:** FastAPI backend + custom async agent orchestration (no LangChain). SQLite persistence. PWA frontend (no build step — vanilla JS, hash-routing). All agents use OpenAI-compatible API.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy + SQLite, aiohttp, PWA (HTML/CSS/JS, Service Worker, Web Push), GitHub.

---

## Complete User Flow (All in UI)

```
1. USER clicks "New Topic" → submits topic title + selects a Profile (or creates one)
        │
2. [Topic Scoping Agent] starts asking questions in the UI:
        │  "Which aspect of the French Revolution interests you most?"
        │  "What time range should we cover?"
        │  "Do you want to focus on causes, events, or aftermath?"
        │  (Interactive: user answers → agent asks follow-ups → continues until clear)
        │
3. After scoping, the agent proposes subtopics:
        │  ├─ ▢ "Causes of the Revolution"        ← user checks which to research NOW
        │  ├─ ☑ "Key Figures & The Reign of Terror"
        │  ├─ ▢ "Napoleon's Rise"
        │  └─ ▢ "Impact on Modern Europe"
        │  (Unchecked → saved as TODO for later)
        │
4. USER selects subtopics to research, clicks "Start Research"
        │
5. [Research Agents] run in parallel (N configurable, each with guardrails)
        │  Status: researching → progress shown in kanban
        │
6. [Compiler Agent] merges all research into comprehensive context
        │  Status: compiling
        │
7. [Writer Agent] creates N histories using the selected Profile (tone/style)
        │  Status: writing → histories_created
        │  Push notification sent to user
        │
8. USER sees histories in Kanban "In Review" column
        │  Clicks → reads markdown
        │  ├── Approve ✅  → status: accepted (ready for YouTube)
        │  ├── Reject ❌   → status: rejected (+ feedback stored)
        │  └── Refine ⟳   → modal: "What should change?"
        │                   → [Editor Agent] refines → back to In Review
        │
9. FEEDBACK LEARNING:
        │  - Each history stores all feedback in its history
        │  - The Profile used is updated: "user liked dramatic tone, rejected dry facts"
        │  - Editor Agent is prompted with past similar feedback
        │
10. SUBTOPIC TODO:
        │  - Unchecked subtopics remain in the topic's backlog
        │  - User can revisit any time and start research on them
        │  - Previous research on the parent topic is reused as context
        │
11. PROFILES:
        │  - "Create Profile" button → Profile Agent asks questions:
        │       "What name?", "What tone? (dramatic/educational/funny)",
        │       "Target audience?", "Preferred length?", "Example style?"
        │  - User answers → Profile saved with embeddings of preferences
        │  - When refining a history, feedback also refines the profile
        │  - User can edit profile questions to update preferences
```

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        PWA Frontend                              │
│                                                                  │
│  ┌────────────┐  ┌──────────────┐  ┌────────────┐  ┌─────────┐  │
│  │ New Topic  │  │ Scoping Chat │  │  Kanban    │  │Profile  │  │
│  │  (form)    │  │  (interactive│  │  Board     │  │Manager  │  │
│  │            │  │   Q&A)       │  │            │  │         │  │
│  └─────┬──────┘  └──────┬───────┘  └─────┬──────┘  └────┬────┘  │
│        │               │                │              │       │
│        └───────────────┴────────────────┴──────────────┘       │
│                            │  REST API (fetch)                  │
└────────────────────────────┼───────────────────────────────────┘
                             │
┌────────────────────────────┼───────────────────────────────────┐
│                     FastAPI Backend                             │
│                            │                                    │
│  ┌─────────────────────────▼─────────────────────────────┐     │
│  │                  Agent Orchestrator                    │     │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐  │     │
│  │  │ Scoping  │  │ Research │  │ Writer   │  │Editor│  │     │
│  │  │  Agent   │  │ Agents(N)│  │ Agent    │  │Agent │  │     │
│  │  └──────────┘  └────┬─────┘  └────┬─────┘  └──┬───┘  │     │
│  │                     │             │            │       │     │
│  │  ┌──────────────────▼─────────────▼────────────▼───┐   │     │
│  │  │              Compiler Agent                      │   │     │
│  │  └──────────────────┬──────────────────────────────┘   │     │
│  │                     │                                   │     │
│  │  ┌──────────────────▼──────────────────────────────┐   │     │
│  │  │         Profile Agent                           │   │     │
│  │  │  (create/edit profiles, learn from feedback)    │   │     │
│  │  └─────────────────────────────────────────────────┘   │     │
│  └────────────────────────────────────────────────────────┘     │
│                            │                                    │
│  ┌─────────────────────────▼─────────────────────────────┐     │
│  │                     SQLite DB                         │     │
│  │  topics | subtopics | histories | profiles | feedback │     │
│  │  push_subscriptions | research_sources                │     │
│  └───────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────┘
```

---

## Database Schema

```sql
-- Topics table
CREATE TABLE topics (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scoping',
        -- scoping → scoping_complete → researching → compiling → writing → histories_created
    profile_id TEXT REFERENCES profiles(id),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Subtopics table
CREATE TABLE subtopics (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id),
    title TEXT NOT NULL,
    description TEXT,               -- What this subtopic covers
    status TEXT NOT NULL DEFAULT 'todo',
        -- todo → selected → researching → researched → done
    todo_order INTEGER DEFAULT 0,   -- Order in the backlog
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Scoping conversation
CREATE TABLE scoping_messages (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id),
    role TEXT NOT NULL,              -- 'agent' or 'user'
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Histories table
CREATE TABLE histories (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topics(id),
    subtopic_id TEXT REFERENCES subtopics(id),
    title TEXT NOT NULL,
    content TEXT NOT NULL,           -- Full markdown
    status TEXT NOT NULL DEFAULT 'in_review',
        -- in_review → refining → accepted | rejected
    profile_id TEXT REFERENCES profiles(id),
    feedback_count INTEGER DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Feedback records (per history + per profile)
CREATE TABLE feedback_records (
    id TEXT PRIMARY KEY,
    history_id TEXT REFERENCES histories(id),
    profile_id TEXT REFERENCES profiles(id),
    feedback_type TEXT NOT NULL,     -- 'accept' | 'reject' | 'refine_request'
    feedback_text TEXT,              -- User's words (null for accept/reject)
    applied BOOLEAN DEFAULT FALSE,   -- Was this feedback used to update the profile?
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Profiles table
CREATE TABLE profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,                -- Brief description
    tone TEXT NOT NULL DEFAULT 'neutral',        -- dramatic, educational, humorous, epic, neutral
    audience TEXT DEFAULT 'general',             -- target audience
    preferred_length TEXT DEFAULT 'medium',      -- short, medium, long
    style_notes TEXT,                -- Free-form style instructions
    creation_feedback TEXT,          -- Answers from Profile Agent questions
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Research sources table
CREATE TABLE research_sources (
    id TEXT PRIMARY KEY,
    subtopic_id TEXT NOT NULL REFERENCES subtopics(id),
    agent_name TEXT NOT NULL,
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

## Agent Descriptions

### 1. Topic Scoping Agent
**Purpose:** Narrows down a broad user topic through interactive Q&A
- Receives topic + profile → generates first question
- User answers via UI chat → agent asks follow-up (up to 5 rounds or until clear)
- After scoping, proposes subtopics: "Based on your answers, these subtopics make sense..."
- User checks which to research NOW, rest go to TODO backlog
- Generates a scoping summary that all subsequent agents use as context

### 2. Research Agents (N configurable)
**Purpose:** Crawl the web for each selected subtopic
- Each subtopic gets its own research agent
- Bounded by guardrails (timeout, pages, chars, queries)
- Returns sources + synthesized findings

### 3. Compiler Agent
**Purpose:** Merge all research outputs into structured context
- Deduplicates across subtopics
- Organizes by theme/timeline
- Produces one comprehensive markdown document

### 4. Writer Agent
**Purpose:** Create N histories from compiled research using a Profile
- Receives: compiled context + selected Profile (tone, style, audience)
- Generates N histories in YouTube-ready markdown format
- Each has: Hook → Narrative → Key Visuals → CTA
- Uses Profile's tone and style guide

### 5. Editor Agent
**Purpose:** Refine a specific history based on user feedback
- Receives: history content + user feedback + profile
- Applies changes while respecting profile tone
- Updates history's feedback_count
- Also suggests profile improvements based on feedback patterns

### 6. Profile Agent
**Purpose:** Create and enhance writing profiles
- **Creation:** Asks user questions (name, tone, audience, length, examples)
- **Enhancement:** User can revisit and answer more questions anytime
- **Feedback Learning:** When histories are accepted/rejected, the profile is updated:
  - "User accepted 3 histories from this profile → reinforcing this tone"
  - "User rejected histories with [pattern] → adjusting profile away from that"

---

## Research Guardrails

| Limit | Default | Config |
|-------|---------|--------|
| Max search queries per agent | 3 | `max_queries_per_agent` |
| Max pages scraped per query | 3 | `max_pages_per_query` |
| Max chars per page | 10,000 | `max_chars_per_page` |
| Max research tokens | 8,000 | `max_research_tokens` |
| Timeout per agent | 60s | `research_timeout_seconds` |
| Max scoping rounds | 5 | `max_scoping_rounds` |

---

## File Structure

```
historiador/
├── pyproject.toml
├── .env.example
├── README.md
│
├── backend/
│   ├── main.py                 # FastAPI app, lifespan, CORS, static files
│   ├── config.py               # Settings from env vars
│   ├── database.py             # SQLAlchemy engine + session
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py             # DeclarativeBase
│   │   ├── topic.py
│   │   ├── subtopic.py
│   │   ├── history.py
│   │   ├── profile.py
│   │   ├── feedback.py
│   │   ├── scoping_message.py
│   │   ├── research_source.py
│   │   └── push_subscription.py
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── topic.py
│   │   ├── subtopic.py
│   │   ├── history.py
│   │   ├── profile.py
│   │   ├── scoping.py
│   │   └── kanban.py
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── topics.py           # POST /topics, GET /topics, GET /topics/:id
│   │   ├── scoping.py          # POST /topics/:id/scoping/answer, GET /scoping/messages
│   │   ├── subtopics.py        # PATCH /subtopics/:id/select, POST /subtopics/:id/research
│   │   ├── histories.py        # GET /histories, PATCH /histories/:id, POST /histories/:id/refine
│   │   ├── kanban.py           # GET /kanban
│   │   ├── profiles.py         # CRUD /profiles, POST /profiles/:id/enhance
│   │   └── notifications.py    # POST /push-subscribe, GET /push-public-key
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── llm_client.py       # Shared OpenAI-compatible client
│   │   ├── scoping_agent.py    # Interactive Q&A to delimit topic
│   │   ├── research_agent.py   # Web crawling + search
│   │   ├── compiler.py         # Merge + deduplicate research
│   │   ├── writer.py           # Generate histories with profile
│   │   ├── editor.py           # Refine histories + profile feedback
│   │   ├── profile_agent.py    # Create+enhance profiles, learn from feedback
│   │   └── orchestrator.py     # Manages full lifecycle
│   │
│   ├── crawler/
│   │   ├── __init__.py
│   │   ├── search.py           # Web search abstraction
│   │   └── scraper.py          # Page content extraction
│   │
│   ├── notifications/
│   │   ├── __init__.py
│   │   └── push.py             # Web push sender
│   │
│   └── migrations/
│       └── init_db.py
│
├── frontend/
│   ├── index.html              # SPA entry point
│   ├── manifest.json           # PWA manifest
│   ├── service-worker.js       # Push + offline cache
│   ├── css/
│   │   └── app.css             # Dark theme, kanban, chat, responsive
│   └── js/
│       ├── app.js              # Router, state, page switching
│       ├── api.js              # Fetch-based API client
│       ├── kanban.js           # Kanban board with columns
│       ├── topic-form.js       # New topic form + profile selector
│       ├── scoping-chat.js     # Interactive Q&A chat UI
│       ├── subtopic-selector.js # Checkbox list for subtopics
│       ├── history-viewer.js   # Markdown render + approve/reject/refine
│       ├── profile-manager.js  # CRUD profiles + enhance questions
│       └── notifications.js    # Push subscription management
│
└── scripts/
    └── run.sh
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| **Topics** | | |
| POST | `/api/topics` | Create topic with title + profile_id |
| GET | `/api/topics` | List all topics with subtopic counts |
| GET | `/api/topics/{id}` | Topic detail with subtopics, histories |
| **Scoping** | | |
| GET | `/api/topics/{id}/scoping/messages` | Get scoping conversation so far |
| POST | `/api/topics/{id}/scoping/answer` | Submit user answer → agent responds |
| POST | `/api/topics/{id}/scoping/complete` | Finalize scoping → propose subtopics |
| **Subtopics** | | |
| GET | `/api/topics/{id}/subtopics` | List subtopics (todo vs selected) |
| PATCH | `/api/subtopics/{id}` | Toggle selected/todo status |
| POST | `/api/topics/{id}/research` | Start research on ALL selected subtopics |
| **Histories** | | |
| GET | `/api/histories` | List with status filter |
| GET | `/api/histories/{id}` | Full history markdown + metadata |
| PATCH | `/api/histories/{id}` | Approve or reject (with optional feedback) |
| POST | `/api/histories/{id}/refine` | Refine with feedback text → Editor Agent |
| **Kanban** | | |
| GET | `/api/kanban` | Board state grouped by status lane |
| GET | `/api/kanban/topic/{id}` | Board state for one topic |
| **Profiles** | | |
| GET | `/api/profiles` | List all profiles |
| POST | `/api/profiles` | Create profile (name only → Profile Agent asks questions) |
| GET | `/api/profiles/{id}` | Profile detail |
| PATCH | `/api/profiles/{id}` | Update profile fields |
| POST | `/api/profiles/{id}/enhance` | Profile Agent asks enhancement questions |
| GET | `/api/profiles/{id}/enhance/questions` | Get next enhancement question |
| POST | `/api/profiles/{id}/enhance/answer` | Answer enhancement question → agent responds |
| **Notifications** | | |
| POST | `/api/push-subscribe` | Register push subscription |
| GET | `/api/push-public-key` | Get VAPID public key |
| **Health** | | |
| GET | `/api/health` | Health check |

---

## UI Screens (Single Page App)

### 1. Main Kanban Screen (default view)
```
┌─────────────────────────────────────────────────────────────────────┐
│  [➕ New Topic]   [📋 Manage Profiles]   [🔔 Notifications]         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────┐ ┌──────────┐ ┌────────┐ ┌─────────┐ ┌──────────┐  │
│  │  Scoping    │ │Research  │ │Writing │ │In Review│ │Accepted   │  │
│  │  (topic)    │ │(subtopic)│ │(topic) │ │(history)│ │(history)  │  │
│  │             │ │          │ │        │ │         │ │           │  │
│  │  "French    │ │Causes    │ │French  │ │"The     │ │"Bastille  │  │
│  │  Rev."      │ │🔥        │ │Rev.    │ │Bastille"│ │Fall" ✅   │  │
│  │             │ │Figures   │ │🔥      │ │"Reign   │ │           │  │
│  │  (scoping)  │ │🔥        │ │        │ │of Terror│ │           │  │
│  └─────────────┘ └──────────┘ └────────┘ └─────────┘ └──────────┘  │
│                                   ┌──────────┐                      │
│                                   │ Rejected │                      │
│                                   │ (history)│                      │
│                                   └──────────┘                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 2. New Topic Screen
```
┌─────────────────────────────────────────────────────────────────────┐
│  [ ← Back to Kanban ]                                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Topic Title: [  ________________________________  ]                │
│                                                                     │
│  Profile:     [ 📖 Epic Storyteller  ▼  ]                           │
│               [ 📚 Educational              ]                        │
│               [ 🎭 Dramatic                 ]                        │
│               [ ➕ Create New Profile...     ]                        │
│                                                                     │
│  [  Start Scoping  ]                                                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3. Scoping Chat Screen
```
┌─────────────────────────────────────────────────────────────────────┐
│  [ ← Back ]   Scoping: "The French Revolution"                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────────────────────────────┐                       │
│  │ Agent: Great topic! Which aspect          │                       │
│  │ interests you most — the causes, the      │                       │
│  │ key events, or the aftermath?             │                       │
│  └──────────────────────────────────────────┘                       │
│  ┌──────────────────────────────────────────┐                       │
│  │ You: I'm most interested in the causes   │                       │
│  │ and how ordinary people were affected.   │                       │
│  └──────────────────────────────────────────┘                       │
│  ┌──────────────────────────────────────────┐                       │
│  │ Agent: Great! And what time range should  │                       │
│  │ we focus on — the decade before 1789 or   │                       │
│  │ the revolutionary period itself?          │                       │
│  └──────────────────────────────────────────┘                       │
│                                                                     │
│  [_______________________________________________] [Send]          │
│                                                   [Complete ✅]     │
└─────────────────────────────────────────────────────────────────────┘
```

### 4. Subtopic Selection Screen
```
┌─────────────────────────────────────────────────────────────────────┐
│  [ ← Back ]   "The French Revolution" — Subtopics                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Based on our conversation, here are the subtopics:                 │
│                                                                     │
│  ☑ Causes of the Revolution (1780-1789)           [Research Now]   │
│  ☑ Life of Ordinary People During the Revolution                    │
│  ▢ The Reign of Terror & Robespierre                                │
│  ▢ Napoleon's Rise to Power                                         │
│  ▢ Impact on European Monarchies                                    │
│                                                                     │
│  Check the ones to research NOW. Unchecked stay as TODO.            │
│                                                                     │
│  [  🚀 Start Research on 2 Selected Subtopics  ]                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 5. History Viewer
```
┌─────────────────────────────────────────────────────────────────────┐
│  [ ← Kanban ]   History: "The Bread That Broke a Kingdom"          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Profile: 📖 Epic Storyteller         Status: In Review             │
│  ───────────────────────────────────────────────────────────────    │
│                                                                     │
│  ## Title: The Bread That Broke a Kingdom                           │
│                                                                     │
│  ## Hook                                                           │
│  In 1788, a French baker...                                        │
│                                                                     │
│  ## Narrative                                                      │
│  ...                                                               │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────────────────────┐  │
│  │ ✅ Accept│  │ ❌ Reject│  │  ⟳  Refine: [                     ]│
│  └──────────┘  └──────────┘  │  [________________________________]│
│                               │  [Send Feedback ⟳]                │
│                               └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 6. Profile Manager
```
┌─────────────────────────────────────────────────────────────────────┐
│  [ ← Back ]   Manage Profiles                                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  📖 Epic Storyteller    (3 histories, 100% acceptance rate)         │
│     [Enhance ✨] [Edit] [Delete]                                    │
│                                                                     │
│  📚 Educational         (1 history, 0% acceptance)                  │
│     [Enhance ✨] [Edit] [Delete]                                    │
│                                                                     │
│  [ ➕ Create New Profile ]                                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Dependency Map

```
BATCH 1 (parallel — independent files):
  Task 1:  Create pyproject.toml + config.py + .env.example
  Task 2:  Create all database models (7 model files)
  Task 3:  Create PWA manifest.json + service-worker.js

BATCH 2 (depends on Batch 1):
  Task 4:  Create database.py + migrations
  Task 5:  Create all Pydantic schemas (topic, subtopic, history, profile, scoping, kanban)

BATCH 3 (depends on Batch 1):
  Task 6:  Create LLM client
  Task 7:  Create crawler/search/scraper
  Task 8:  Create push notification module

BATCH 4 (depends on Batch 3):
  Task 9:  Create Scoping Agent
  Task 10: Create Research Agent (with guardrails)
  Task 11: Create Profile Agent

BATCH 5 (depends on Batch 4):
  Task 12: Create Compiler Agent
  Task 13: Create Writer Agent (uses profiles)
  Task 14: Create Editor Agent (with feedback learning)

BATCH 6 (depends on Batch 5):
  Task 15: Create Orchestrator (full pipeline orchestration)

BATCH 7 (depends on Batch 2, 6):
  Task 16: Create routers — topics + scoping + subtopics
  Task 17: Create routers — histories + kanban + profiles
  Task 18: Create router — notifications

BATCH 8 (depends on Batch 7):
  Task 19: Create FastAPI main.py (wire everything)

BATCH 9 (parallel — frontend base):
  Task 20: Create frontend CSS (dark theme, kanban columns, chat bubbles, responsive)
  Task 21: Create api.js + notifications.js
  Task 22: Create index.html + manifest service worker finalization

BATCH 10 (depends on Batch 9):
  Task 23: Create topic-form.js + scoping-chat.js
  Task 24: Create subtopic-selector.js
  Task 25: Create kanban.js

BATCH 11 (depends on Batch 10):
  Task 26: Create history-viewer.js
  Task 27: Create profile-manager.js

BATCH 12 (depends on Batch 11):
  Task 28: Wire up app.js (router, state, page switching, auto-refresh)

BATCH 13:
  Task 29: Create README.md + run.sh
  Task 30: End-to-end test
```

---

## Detailed Tasks

### Task 1: Create pyproject.toml, config.py, .env.example

**Objective:** Set up Python project with uv, all dependencies, and typed settings

**Files:**
- Create: `pyproject.toml` — same deps as before
- Create: `backend/__init__.py`
- Create: `backend/config.py`

**Config additions vs previous version:**
```python
# Agent config
default_num_histories: int = 2
default_num_research_agents: int = 3
max_scoping_rounds: int = 5

# Research Guardrails
max_queries_per_agent: int = 3
max_pages_per_query: int = 3
max_chars_per_page: int = 10_000
max_research_tokens: int = 8_000
research_timeout_seconds: int = 60
```

---

### Task 2: Create all database models

**Objective:** 7 SQLAlchemy ORM models matching the schema above

**Files:**
- Create: `backend/models/__init__.py`
- Create: `backend/models/base.py` — shared DeclarativeBase
- Create: `backend/models/topic.py`
- Create: `backend/models/subtopic.py`
- Create: `backend/models/history.py`
- Create: `backend/models/profile.py`
- Create: `backend/models/feedback.py`
- Create: `backend/models/scoping_message.py`
- Create: `backend/models/research_source.py`
- Create: `backend/models/push_subscription.py`

---

### Task 3: Create PWA manifest.json + service-worker.js

**Objective:** PWA foundation — installable, push-capable, offline-ready

**Files:**
- Create: `frontend/manifest.json`
- Create: `frontend/service-worker.js`

---

### Task 4: Create database.py + migrations

**Objective:** Async SQLAlchemy engine, session factory, table creation

**Files:**
- Create: `backend/database.py`
- Create: `backend/migrations/__init__.py`
- Create: `backend/migrations/init_db.py`

---

### Task 5: Create all Pydantic schemas

**Objective:** Request/response schemas for all API endpoints

**Files:**
- Create: `backend/schemas/__init__.py`
- Create: `backend/schemas/topic.py`
- Create: `backend/schemas/subtopic.py`
- Create: `backend/schemas/history.py`
- Create: `backend/schemas/profile.py`
- Create: `backend/schemas/scoping.py`
- Create: `backend/schemas/kanban.py`

**Scoping schemas:**
```python
class ScopingAnswer(BaseModel):
    topic_id: str
    answer: str

class ScopingMessageResponse(BaseModel):
    id: str
    role: str  # 'agent' | 'user'
    content: str
    created_at: datetime

class SubtopicProposal(BaseModel):
    subtopics: list[SubtopicCreate]

class ScopingComplete(BaseModel):
    scoping_summary: str
    proposed_subtopics: list[SubtopicCreate]
```

---

### Task 6: Create LLM client

**Objective:** Shared HTTP client for OpenAI-compatible API

**Files:**
- Create: `backend/agents/__init__.py`
- Create: `backend/agents/llm_client.py`

Uses httpx with streaming for chat interactions. Supports both one-shot and streaming modes.

---

### Task 7: Create crawler/search/scraper

**Files:**
- Create: `backend/crawler/__init__.py`
- Create: `backend/crawler/search.py`
- Create: `backend/crawler/scraper.py`

Three search backends: Tavily, SerpAPI, DuckDuckGo fallback.
Uses aiohttp for async HTTP, BeautifulSoup for extraction.

---

### Task 8: Create push notification module

**Files:**
- Create: `backend/notifications/__init__.py`
- Create: `backend/notifications/push.py`

Sends via pywebpush. Triggered when histories reach "in_review" status.

---

### Task 9: Create Scoping Agent

**Objective:** Interactive Q&A to delimit a broad topic, then propose subtopics

**Files:**
- Create: `backend/agents/scoping_agent.py`

**Behavior:**
1. User submits topic + profile → Scoping Agent generates first question
2. Question stored in `scoping_messages` table (role='agent')
3. User answers → stored (role='user') → agent generates follow-up
4. After each answer, agent decides: "ask more" or "I have enough context"
5. Max `max_scoping_rounds` rounds (default 5)
6. When finalized → agent generates:
   - `scoping_summary` — concise context for all downstream agents
   - `proposed_subtopics` — list of 3-5 subtopics with descriptions
   - these are returned to the UI and saved as Subtopic records (status='todo')

**LLM prompt structure:**
- System: "You are a topic scoping assistant. Your job is to ask questions..."
- Previous messages: full scoping conversation
- Output (when ready): JSON with { "ready": true, "summary": "...", "subtopics": [...] }

**Interactive via API:**
- POST `/api/topics/{id}/scoping/answer` → agent processes → returns next question or completion
- The UI polls or receives the response and renders the chat

---

### Task 10: Create Research Agent (with guardrails)

**Objective:** Crawl web for a specific subtopic, bounded by hard limits

**Files:**
- Create: `backend/agents/research_agent.py`

Per subtopic. Runs asyncio.gather() for queries, capped at max_pages_per_query per query. Wrapped in asyncio.wait_for(timeout=research_timeout_seconds). Returns whatever it found if timeout hits.

---

### Task 11: Create Profile Agent

**Objective:** Create, enhance, and learn-from-feedback for writing profiles

**Files:**
- Create: `backend/agents/profile_agent.py`

**Creation flow:**
1. User creates profile with just a name
2. Profile Agent generates first question: "What tone do you want? (dramatic, educational, humorous, epic, neutral)"
3. User answers → agent asks follow-ups (name, audience, length, style examples)
4. After enough answers, profile is populated with structured fields

**Enhancement flow:**
- User clicks "Enhance ✨" on a profile
- Agent reviews current profile stats (acceptance rate, patterns in feedback) and asks targeted questions
- Answers update the profile's style_notes and creation_feedback

**Feedback learning:**
When a history that used this profile is accepted or rejected:
- If accepted → profile is reinforced (stored in creation_feedback)
- If rejected → agent analyzes the rejection pattern and suggests adjustments
- If multiple rejections with same pattern → profile tone/style is automatically adjusted

---

### Task 12: Create Compiler Agent

**Objective:** Merge research from all subtopics into one structured context

**Files:**
- Create: `backend/agents/compiler.py`

Takes all ResearchResult objects, deduplicates by URL, organizes by theme.

---

### Task 13: Create Writer Agent (with profiles)

**Objective:** Generate N histories using a specific profile

**Files:**
- Create: `backend/agents/writer.py`

```python
class WriterAgent:
    async def write_histories(
        self,
        compiled_context: str,
        scoping_summary: str,
        profile: Profile,
        n: int = 2,
    ) -> list[History]:
        """Generate N histories with the profile's tone and style."""
```

The system prompt includes the profile's full configuration: tone, audience, length, style_notes, creation_feedback (past learnings).

---

### Task 14: Create Editor Agent (with feedback learning)

**Objective:** Refine a history based on user feedback, update profile

**Files:**
- Create: `backend/agents/editor.py`

```python
class EditorAgent:
    async def refine(
        self,
        history_content: str,
        feedback: str,
        profile: Profile,
        past_feedback: list[str],  # Similar past feedback for context
    ) -> tuple[str, str | None]:
        """Returns (refined_markdown, profile_suggestion_or_None)."""
        # If feedback pattern matches previous rejections → suggest profile tweak
```

---

### Task 15: Create Orchestrator

**Objective:** Coordinate the entire lifecycle per topic

**Files:**
- Create: `backend/agents/orchestrator.py`

```python
class Orchestrator:
    async def run_research(self, topic_id: str):
        """Full pipeline for a topic after scoping is complete:
        1. status = researching
        2. For each SELECTED subtopic: spawn ResearchAgent (parallel)
        3. status = compiling → CompilerAgent
        4. status = writing → WriterAgent with profile
        5. status = histories_created → save histories → push notification
        """
```

---

### Task 16-18: Create all API routers

**Files:**
- `backend/routers/topics.py` — CRUD + scoping endpoints
- `backend/routers/subtopics.py` — select/deselect, trigger research
- `backend/routers/histories.py` — CRUD + refine + approve/reject
- `backend/routers/kanban.py` — board state
- `backend/routers/profiles.py` — CRUD + enhance
- `backend/routers/notifications.py` — push subscription

---

### Task 19: Create FastAPI main.py

**Objective:** Wire everything up

**Files:**
- Create: `backend/main.py`

Mounts static files at `/`, includes all routers, CORS, lifespan (creates tables).

---

### Task 20-28: Frontend

**20: CSS** — Dark theme. CSS variables for colors. Kanban columns as flexbox. Chat bubbles. Responsive.

**21: api.js + notifications.js** — Fetch-based API client with `getTopcis()`, `submitAnswer()`, `approveHistory()`, etc.

**22: index.html + finalize PWA** — SPA shell with nav, content div for hash-based routing.

**23: topic-form.js + scoping-chat.js** — New topic form. Interactive chat UI with message bubbles.

**24: subtopic-selector.js** — Checkbox list with descriptions, "Research Now" action.

**25: kanban.js** — Columns: Scoping → Researching → Compiling → Writing → In Review → Accepted → Rejected. Cards show title, subtitle, status icon. Auto-refreshes every 5s while agents are running.

**26: history-viewer.js** — Renders markdown (simple regex-based or marked library). Approve/Reject/Refine buttons. Refinement modal with textarea.

**27: profile-manager.js** — List profiles with stats. Create new. Enhance button. Acceptance rates.

**28: app.js** — Hash router: #kanban, #new-topic, #scoping/:id, #subtopics/:id, #history/:id, #profiles. Auto-refresh kanban. Service worker registration.

---

### Task 29: README.md + run.sh

**README**: Setup instructions, env vars, how to run, architecture overview.

**run.sh**: 
```bash
#!/bin/bash
cd "$(dirname "$0")/.."
uv sync
uv run uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

---

### Task 30: End-to-end test

1. `uv sync && uv run uvicorn backend.main:app --port 8000`
2. Open browser → should see Kanban board
3. Create topic "The French Revolution" with profile "Epic Storyteller"
4. Should enter scoping chat — answer questions
5. Complete scoping → subtopics appear
6. Select 2, start research
7. Wait for histories to appear (poll kanban)
8. Open a history → markdown rendered → Approve/Reject/Refine
9. Create a new profile → enhance with questions
10. Verify subtopic TODO items persist for next time