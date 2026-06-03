"""Editor agent that reviews and refines written histories."""
from typing import Optional
from backend.llm_client import LLMClient

EDITOR_SYSTEM_PROMPT = """You are the Editor Agent for Historiador.
Review a written history and provide feedback OR incorporate feedback to refine it.

MODE: "review" — Check the history for:
1. Historical accuracy (flag anything unsupported by sources)
2. Tone consistency (does it match the profile?)
3. Structure (clear sections, good flow)
4. Engagement (compelling opening, narrative drive)
5. Length appropriateness
Output JSON: {"score": 1-10, "strengths": [...], "issues": [...], "suggestions": [...], "verdict": "accept"/"minor_revision"/"major_revision"}

MODE: "refine" — Given the original history and user feedback, produce an improved version."""

class EditorAgent:
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()

    async def review(self, history_content: str, sources: list[dict], tone: str = "neutral") -> dict:
        sources_text = "\n".join(f"[{i+1}] {s.get('title', '')}" for i, s in enumerate(sources[:5]))
        prompt = f"Tone: {tone}\nSources:\n{sources_text}\n\nHistory:\n{history_content[:4000]}\n\nReview this history."
        messages = [{"role": "system", "content": EDITOR_SYSTEM_PROMPT + "\nMode: review"}, {"role": "user", "content": prompt}]
        return await self.llm.structured_chat(messages, dict, temperature=0.4)

    async def refine(self, history_content: str, feedback: str, tone: str = "neutral") -> str:
        prompt = f"Tone: {tone}\n\nOriginal History:\n{history_content}\n\nFeedback:\n{feedback}\n\nRefine the history based on this feedback."
        messages = [{"role": "system", "content": EDITOR_SYSTEM_PROMPT + "\nMode: refine"}, {"role": "user", "content": prompt}]
        return await self.llm.chat(messages, temperature=0.6, max_tokens=4096)