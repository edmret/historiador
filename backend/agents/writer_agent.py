"""Writer agent that produces markdown histories from outlines."""
from typing import Optional
from backend.llm_client import LLMClient

WRITER_SYSTEM_PROMPT = """You are the Writer Agent for Historiador.
Given an outline and research sources, write a compelling narrative history in markdown.
Follow the outline sections but write flowing prose, not bullet points.
Adapt tone to the specified profile (dramatic, educational, humorous, epic, or neutral).
Write for the specified audience level.
Target the specified length (short = ~300 words, medium = ~800 words, long = ~1500 words).
Use markdown formatting: ## for section headings, **bold** for emphasis, *italic* for terms.
Include relevant dates, names, and facts from the research.
Do NOT fabricate information not present in the research sources."""

class WriterAgent:
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()

    async def write(
        self,
        subtopic_title: str,
        outline: dict,
        sources: list[dict],
        tone: str = "neutral",
        audience: str = "general",
        length: str = "medium",
        style_notes: str = "",
    ) -> str:
        outline_str = f"Title: {outline.get('title', subtopic_title)}\n"
        for sec in outline.get("sections", []):
            outline_str += f"\n## {sec.get('heading', '')}\n"
            for kp in sec.get("key_points", []):
                outline_str += f"- {kp}\n"

        sources_text = "\n\n".join(
            f"[{i+1}] {s.get('title', '')}: {s.get('content_snippet', '')[:1500]}"
            for i, s in enumerate(sources[:8])
        )

        prompt = f"Subtopic: {subtopic_title}\nTone: {tone}\nAudience: {audience}\nLength: {length}\nStyle Notes: {style_notes}\n\nOutline:\n{outline_str}\n\nResearch Sources:\n{sources_text}\n\nWrite the history now."
        messages = [{"role": "system", "content": WRITER_SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        return await self.llm.chat(messages, temperature=0.8, max_tokens=4096)