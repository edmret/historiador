from typing import Optional
import aiohttp
from bs4 import BeautifulSoup
from backend.config import settings


class WebScraper:
    """Scrape and extract text content from web pages."""

    MAX_CHARS = settings.max_chars_per_page

    async def scrape(self, url: str) -> Optional[str]:
        """Fetch and extract readable text from a URL."""
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; Historiador/0.1; +https://historiador.app)",
        }
        try:
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    html = await resp.text()
                    soup = BeautifulSoup(html, "lxml")
                    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                        tag.decompose()
                    text = soup.get_text(separator="\n", strip=True)
                    return text[:self.MAX_CHARS]
        except (aiohttp.ClientError, Exception):
            return None