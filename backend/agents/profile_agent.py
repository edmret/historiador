"""Profile agent that creates writing profiles via Q&A."""
from backend.llm_client import LLMClient

PROFILE_SYSTEM_PROMPT = """You are the Profile Agent for Historiador.
Your job is to create writing profiles by asking the user questions.
A profile defines: tone (dramatic/educational/humorous/epic/neutral), audience, preferred length (short/medium/long), and style notes.

Ask ONE question at a time. Cover: desired tone, target audience, length preference, any specific style notes.
After enough info, output exactly: "[PROFILE_COMPLETE]" followed by a JSON with fields: name, description, tone, audience, preferred_length, style_notes."""

class ProfileAgent:
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()

    async def generate_question(self, conversation_history: list[dict]) -> str:
        messages = [{"role": "system", "content": PROFILE_SYSTEM_PROMPT}] + conversation_history
        return await self.llm.chat(messages, temperature=0.7)

    async def process_response(self, conversation_history: list[dict], user_message: str) -> dict:
        enriched = conversation_history + [{"role": "user", "content": user_message}]
        messages = [{"role": "system", "content": PROFILE_SYSTEM_PROMPT}] + enriched
        response = await self.llm.chat(messages, temperature=0.7)

        if "[PROFILE_COMPLETE]" in response:
            import json
            json_str = response.split("[PROFILE_COMPLETE]")[1].strip()
            try:
                summary = json.loads(json_str)
            except json.JSONDecodeError:
                import re
                match = re.search(r"\{.*\}", json_str, re.DOTALL)
                summary = json.loads(match.group()) if match else {}
            return {"complete": True, "agent_message": response, "profile_data": summary}

        return {"complete": False, "agent_message": response}
