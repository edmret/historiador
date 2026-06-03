"""Research agent that searches the web and scrapes content for a subtopic."""
import asyncio
from typing import Optional
from backend.llm_client import LLMClient
from backend.crawler.searcher import WebSearcher
from backend.crawler.scraper import WebScraper
from backend.config import settings

RESEARCH_SYSTEM_PROMPT = """You are a Research Agent for Historiador.
Given a subtopic and optional context, generate search queries to find relevant information.
Output only the queries as a JSON array of strings: ["query1", "query2", "query3"]
Generate 1-3 queries that cover different angles of the subtopic."""

class ResearchAgent:
    def __init__(
        self,
        name: str = "researcher",
        llm_client: LLMClient | None = None,
        searcher: WebSearcher | None = None,
        scraper: WebScraper | None = None,
    ):
        self.name = name
        self.llm = llm_client or LLMClient()
        self.searcher = searcher or WebSearcher()
        self.scraper = scraper or WebScraper()
        self.max_queries = settings.max_queries_per_agent
        self.max_pages = settings.max_pages_per_query
        self.max_chars = settings.max_chars_per_page
        self.timeout = settings.research_timeout_seconds

    async def generate_queries(self, subtopic_title: str, subtopic_description: str = "", context: str = "") -> list[str]:
        prompt = f"Subtopic: {subtopic_title}\nDescription: {subtopic_description}\nContext: {context}"
        messages = [{"role": "system", "content": RESEARCH_SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        try:
            response = await asyncio.wait_for(
                self.llm.chat(messages, temperature=0.7, max_tokens=500),
                timeout=self.timeout,
            )
            import json, re
            match = re.search(r"\[.*?\]", response, re.DOTALL)
            if match:
                queries = json.loads(match.group())
                return queries[:self.max_queries]
            return [subtopic_title]
        except (asyncio.TimeoutError, Exception):
            return [subtopic_title]

    async def research(self, subtopic_title: str, subtopic_description: str = "", context: str = "") -> list[dict]:
        """Research a subtopic and return list of source dicts with url, title, content_snippet."""
        queries = await self.generate_queries(subtopic_title, subtopic_description, context)
        sources = []
        seen_urls = set()

        for query in queries:
            try:
                results = await asyncio.wait_for(
                    self.searcher.search(query, self.max_pages),
                    timeout=15.0,
                )
            except (asyncio.TimeoutError, Exception):
                continue

            for result in results:
                url = result.get("url", "")
                if url in seen_urls or not url:
                    continue
                seen_urls.add(url)

                content = await self.scraper.scrape(url) if url else None
                sources.append({
                    "agent_name": self.name,
                    "url": url,
                    "title": result.get("title", ""),
                    "content_snippet": (content[:self.max_chars] if content else result.get("snippet", "")),
                })

                if len(sources) >= self.max_queries * self.max_pages:
                    return sources

        return sources