"""Compiler agent that synthesizes research into structured outlines."""
from typing import Optional
from backend.llm_client import LLMClient

COMPILER_SYSTEM_PROMPT = """You are the Compiler Agent for Historiador.
Given research sources for a subtopic, synthesize them into a structured outline for writing.
Output a JSON object with:
- "title": the proposed history title
- "sections": list of section objects with "heading" and "key_points" (list of strings)
- "estimated_length": "short"/"medium"/"long"
- "source_count": number of unique sources used"""

class CompilerAgent:
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()

    async def compile(self, subtopic_title: str, sources: list[dict], tone: str = "neutral", audience: str = "general") -> dict:
        sources_text = "\n\n".join(
            f"Source {i+1} ({s.get('title', '')}):\n{s.get('content_snippet', '')[:2000]}"
            for i, s in enumerate(sources[:10])
        )
        prompt = f"Subtopic: {subtopic_title}\nTone: {tone}\nAudience: {audience}\n\nResearch Sources:\n{sources_text}\n\nCreate a structured outline."
        messages = [{"role": "system", "content": COMPILER_SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
        return await self.llm.structured_chat(messages, dict, temperature=0.5)