"""Pluggable web search adapter pattern.

Supported providers (configured via SEARCH_PROVIDER env var):
  - duckduckgo   Free, no API key (default). Uses duckduckgo_search lib.
  - direct       Free, no API key. Scrapes DuckDuckGo HTML results directly.
  - hermes       Uses a Hermes CLI subagent with the 'web' toolset.
  - tavily       Tavily Search API (requires TAVILY_API_KEY).
  - serpapi      SerpAPI Google results (requires SERPAPI_API_KEY).
  - mock         No-op fallback returning Wikipedia links.

Set SEARCH_PROVIDER=duckduckgo (or direct/hermes/tavily/serpapi/mock)
in .env to choose the active provider.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from backend.config import settings

logger = logging.getLogger(__name__)


# ── Abstract base ──────────────────────────────────────────────────────────

class SearchProvider(ABC):
    """Interface for all search backends."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 3) -> list[dict]:
        """Return list of {url, title, snippet} dicts."""


# ── DuckDuckGo adapter (free, no API key) ──────────────────────────────────

class DuckDuckGoSearcher(SearchProvider):
    """Search via the `duckduckgo_search` Python library."""

    async def search(self, query: str, max_results: int = 3) -> list[dict]:
        try:
            try:
                from ddgs import DDGS  # type: ignore  # ddgs (renamed package)
            except ImportError:
                from duckduckgo_search import DDGS  # type: ignore  # legacy package
        except ImportError:
            logger.warning("ddgs/duckduckgo_search not installed — falling back to mock")
            return await _mock_search(query, max_results)

        def _sync_search():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))

        try:
            results = await asyncio.to_thread(_sync_search)
            return [
                {
                    "url": r.get("href", ""),
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                }
                for r in results
            ]
        except Exception as exc:
            logger.error("DuckDuckGo search failed: %s", exc)
            return await _mock_search(query, max_results)


# ── Direct DuckDuckGo HTML scraper (free, zero deps beyond httpx+bs4) ──────

class DirectDuckDuckGoSearcher(SearchProvider):
    """Scrape DuckDuckGo HTML results directly — no API key needed."""

    _HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    }

    async def search(self, query: str, max_results: int = 3) -> list[dict]:
        url = "https://html.duckduckgo.com/html/"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                data={"q": query, "bt": ""},
                headers=self._HEADERS,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

        results: list[dict] = []
        for row in soup.select("result")[:max_results]:
            results.append({
                "url": row.select_one("a.result-a").get("href", "") if row.select_one("a.result-a") else "",
                "title": row.select_one("a.result-a").get_text(strip=True) if row.select_one("a.result-a") else "",
                "snippet": row.select_one("result-snippet").get_text(strip=True) if row.select_one("result-snippet") else "",
            })
        return results if results else await _mock_search(query, max_results)


# ── Hermes CLI subagent adapter ─────────────────────────────────────────────

class HermesAgentSearcher(SearchProvider):
    """Dispatch a Hermes CLI subagent with the 'web' toolset to search."""

    async def search(self, query: str, max_results: int = 3) -> list[dict]:
        # Build a prompt that tells Hermes to do a web search and return JSON
        prompt = (
            f"Search the web for '{query}'. "
            f"Return exactly {max_results} results as a JSON array of objects "
            f"with keys: url, title, snippet. "
            f"Only output valid JSON, nothing else."
        )
        cmd = f'hermes chat -q "{prompt}" --toolsets web --quiet'
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45.0)
            output = stdout.decode().strip()

            # Try to extract JSON from the output
            json_match = re.search(r"\[[\s\S]*\]", output)
            if json_match:
                data = json.loads(json_match.group())
                return data
        except Exception as exc:
            logger.error("Hermes subagent search failed: %s", exc)
        return await _mock_search(query, max_results)


# ── Tavily adapter (paid, requires API key) ────────────────────────────────

class TavilySearcher(SearchProvider):
    async def search(self, query: str, max_results: int = 3) -> list[dict]:
        api_key = settings.tavily_api_key or ""
        if not api_key:
            logger.warning("Tavily API key not configured — falling back to mock")
            return await _mock_search(query, max_results)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "max_results": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"url": r.get("url"), "title": r.get("title"), "snippet": r.get("content", "")}
                for r in data.get("results", [])
            ]


# ── SerpAPI adapter (paid, requires API key) ───────────────────────────────

class SerpAPISearcher(SearchProvider):
    async def search(self, query: str, max_results: int = 3) -> list[dict]:
        api_key = settings.serpapi_api_key or ""
        if not api_key:
            logger.warning("SerpAPI key not configured — falling back to mock")
            return await _mock_search(query, max_results)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://serpapi.com/search",
                params={"api_key": api_key, "q": query, "engine": "google", "num": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"url": r.get("link"), "title": r.get("title"), "snippet": r.get("snippet", "")}
                for r in data.get("organic_results", [])
            ]


# ── Mock fallback ──────────────────────────────────────────────────────────

async def _mock_search(query: str, max_results: int = 3) -> list[dict]:
    return [
        {
            "url": f"https://en.wikipedia.org/wiki/{query.replace(' ', '_')}",
            "title": f"{query} - Wikipedia",
            "snippet": f"Information about {query} from Wikipedia.",
        },
        {
            "url": f"https://www.britannica.com/search?query={query}",
            "title": f"{query} | Britannica",
            "snippet": f"Encyclopedia entry about {query}.",
        },
    ][:max_results]


# ── Factory ────────────────────────────────────────────────────────────────

_PROVIDER_MAP: dict[str, type[SearchProvider]] = {
    "duckduckgo": DuckDuckGoSearcher,
    "direct": DirectDuckDuckGoSearcher,
    "hermes": HermesAgentSearcher,
    "tavily": TavilySearcher,
    "serpapi": SerpAPISearcher,
    "mock": type("MockSearcher", (SearchProvider,), {
        "search": staticmethod(_mock_search),
    }),
}


def get_searcher(provider: Optional[str] = None) -> SearchProvider:
    """Return a SearchProvider instance based on the configured provider."""
    name = (provider or settings.search_provider).lower()
    cls = _PROVIDER_MAP.get(name)
    if cls is None:
        logger.warning("Unknown search provider '%s', defaulting to duckduckgo", name)
        cls = DuckDuckGoSearcher
    return cls()


# ── Backward-compatible alias ──────────────────────────────────────────────

class WebSearcher(SearchProvider):
    """Backward-compatible wrapper around the factory.

    Usage is identical to the old WebSearcher:
        searcher = WebSearcher()           # uses settings.search_provider
        searcher = WebSearcher("duckduckgo")  # override
        results = await searcher.search("history of Rome", max_results=3)
    """

    def __init__(self, provider: Optional[str] = None):
        self._provider = provider

    async def search(self, query: str, max_results: int = 3) -> list[dict]:
        return await get_searcher(self._provider).search(query, max_results)
