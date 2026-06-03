import json
from typing import Optional
import httpx
from backend.config import settings


class WebSearcher:
    """Search the web using configured search provider."""

    def __init__(self, provider: str = "tavily"):
        self.provider = provider.lower()

    async def search(self, query: str, max_results: int = 3) -> list[dict]:
        """Search and return list of {url, title, snippet} dicts."""
        if self.provider == "serpapi":
            return await self._search_serpapi(query, max_results)
        return await self._search_tavily(query, max_results)

    async def _search_tavily(self, query: str, max_results: int) -> list[dict]:
        api_key = settings.tavily_api_key or ""
        if not api_key:
            return await self._mock_search(query, max_results)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "max_results": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            return [{"url": r.get("url"), "title": r.get("title"), "snippet": r.get("content", "")} for r in data.get("results", [])]

    async def _search_serpapi(self, query: str, max_results: int) -> list[dict]:
        api_key = settings.serpapi_api_key or ""
        if not api_key:
            return await self._mock_search(query, max_results)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://serpapi.com/search",
                params={"api_key": api_key, "q": query, "engine": "google", "num": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            results = []
            for r in data.get("organic_results", []):
                results.append({"url": r.get("link"), "title": r.get("title"), "snippet": r.get("snippet", "")})
            return results

    async def _mock_search(self, query: str, max_results: int) -> list[dict]:
        """Fallback mock search when no API key is configured."""
        return [
            {"url": f"https://en.wikipedia.org/wiki/{query.replace(' ', '_')}", "title": f"{query} - Wikipedia", "snippet": f"Information about {query} from Wikipedia."},
            {"url": f"https://www.britannica.com/search?query={query}", "title": f"{query} | Britannica", "snippet": f"Encyclopedia entry about {query}."},
        ][:max_results]