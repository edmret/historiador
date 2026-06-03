"""Interactive scoping agent that refines a topic via Q&A."""
from backend.llm_client import LLMClient

SCOPING_SYSTEM_PROMPT = """You are the Scoping Agent for Historiador, a history generation system.
Your job is to help the user refine their topic by asking targeted questions.
Guide the user to define: scope, time period, key figures/events, geographic focus, and target audience.
Keep responses conversational.
After the user has provided enough detail, output exactly: "[SCOPING_COMPLETE]" followed by a JSON summary with fields: refined_title, description, suggested_subtopics (list of 3-8 objects with title and description), time_period, geographic_focus, target_audience.

Rules:
- Ask ONE question at a time.
- Extract subtopics the user mentions naturally.
- Cover: time period, geography, angle/focus, audience.
- After 3-5 exchanges, declare scoping complete with the JSON blob."""

class ScopingAgent:
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()

    async def generate_question(self, conversation_history: list[dict]) -> str:
        messages = [{"role": "system", "content": SCOPING_SYSTEM_PROMPT}] + conversation_history
        return await self.llm.chat(messages, temperature=0.7)

    async def process_response(self, conversation_history: list[dict], user_message: str) -> dict:
        enriched = conversation_history + [{"role": "user", "content": user_message}]
        messages = [{"role": "system", "content": SCOPING_SYSTEM_PROMPT}] + enriched
        response = await self.llm.chat(messages, temperature=0.7)

        if "[SCOPING_COMPLETE]" in response:
            import json
            json_str = response.split("[SCOPING_COMPLETE]")[1].strip()
            try:
                summary = json.loads(json_str)
            except json.JSONDecodeError:
                import re
                match = re.search(r"\{.*\}", json_str, re.DOTALL)
                summary = json.loads(match.group()) if match else {}
            return {"complete": True, "agent_message": response, "summary": summary, "enriched_history": enriched + [{"role": "assistant", "content": response}]}

        return {"complete": False, "agent_message": response, "enriched_history": enriched + [{"role": "assistant", "content": response}]}
