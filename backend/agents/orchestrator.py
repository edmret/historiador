"""HistoriadorOrchestrator — coordinates the full multi-agent pipeline."""
import asyncio
import json
from typing import Optional
from sqlalchemy import select, update as sql_update
from datetime import datetime, timezone

from backend.database import async_session
from backend.models.topic import Topic
from backend.models.subtopic import Subtopic
from backend.models.history import History
from backend.models.profile import Profile
from backend.models.scoping_message import ScopingMessage
from backend.models.research_source import ResearchSource
from backend.models.feedback import FeedbackRecord
from backend.llm_client import LLMClient
from backend.crawler.searcher import WebSearcher
from backend.crawler.scraper import WebScraper
from backend.agents.scoping_agent import ScopingAgent
from backend.agents.research_agent import ResearchAgent
from backend.agents.profile_agent import ProfileAgent
from backend.agents.compiler_agent import CompilerAgent
from backend.agents.writer_agent import WriterAgent
from backend.agents.editor_agent import EditorAgent
from backend.notifications.push import PushNotifier
from backend.config import settings
from backend.services.app_config_service import get_app_config_service


class HistoriadorOrchestrator:
    """Orchestrates the multi-agent history generation pipeline."""

    def __init__(self):
        app_config = get_app_config_service()

        self.scoping_llm = LLMClient(config=app_config.get_agent_config_sync("scoping"))
        self.research_llm = LLMClient(config=app_config.get_agent_config_sync("research"))
        self.compiler_llm = LLMClient(config=app_config.get_agent_config_sync("compiler"))
        self.writer_llm = LLMClient(config=app_config.get_agent_config_sync("writer"))
        self.editor_llm = LLMClient(config=app_config.get_agent_config_sync("editor"))
        self.profile_llm = LLMClient(config=app_config.get_agent_config_sync("profile"))

        self.scoping_agent = ScopingAgent(self.scoping_llm)
        self.research_agent_factory = lambda name: ResearchAgent(name, self.research_llm)
        self.profile_agent = ProfileAgent(self.profile_llm)
        self.compiler = CompilerAgent(self.compiler_llm)
        self.writer = WriterAgent(self.writer_llm)
        self.editor = EditorAgent(self.editor_llm)
        self.notifier = PushNotifier()

    # --- Topic Creation & Scoping ---

    async def create_topic(self, title: str) -> Topic:
        async with async_session() as session:
            topic = Topic(title=title, status="scoping")
            session.add(topic)
            await session.commit()
            await session.refresh(topic)
            return topic

    async def add_scoping_message(self, topic_id: str, role: str, content: str) -> ScopingMessage:
        async with async_session() as session:
            msg = ScopingMessage(topic_id=topic_id, role=role, content=content)
            session.add(msg)
            await session.commit()
            await session.refresh(msg)
            return msg

    async def get_scoping_history(self, topic_id: str) -> list[dict]:
        async with async_session() as session:
            result = await session.execute(
                select(ScopingMessage).where(ScopingMessage.topic_id == topic_id).order_by(ScopingMessage.created_at)
            )
            return [{"role": m.role, "content": m.content} for m in result.scalars().all()]

    async def process_scoping(self, topic_id: str, user_message: str) -> dict:
        history = await self.get_scoping_history(topic_id)
        result = await self.scoping_agent.process_response(history, user_message)
        await self.add_scoping_message(topic_id, "user", user_message)
        await self.add_scoping_message(topic_id, "agent", result["agent_message"])

        if result.get("complete"):
            summary = result.get("summary", {})
            subtopics = summary.get("suggested_subtopics", [])
            async with async_session() as session:
                topic = await session.get(Topic, topic_id)
                if topic:
                    topic.status = "scoping_complete"
                    for i, st in enumerate(subtopics):
                        sub = Subtopic(
                            topic_id=topic_id,
                            title=st.get("title", f"Subtopic {i+1}"),
                            description=st.get("description", ""),
                            todo_order=i,
                            status="todo",
                        )
                        session.add(sub)
                    await session.commit()
            return {"complete": True, "summary": summary}
        return {"complete": False, "agent_message": result["agent_message"]}

    # --- Profile Creation ---

    async def process_profile_creation(self, conversation_history: list[dict], user_message: str) -> dict:
        result = await self.profile_agent.process_response(conversation_history, user_message)
        if result.get("complete"):
            data = result["profile_data"]
            async with async_session() as session:
                profile = Profile(
                    name=data.get("name", "Custom Profile"),
                    description=data.get("description", ""),
                    tone=data.get("tone", "neutral"),
                    audience=data.get("audience", "general"),
                    preferred_length=data.get("preferred_length", "medium"),
                    style_notes=data.get("style_notes", ""),
                    creation_feedback=json.dumps(conversation_history),
                )
                session.add(profile)
                await session.commit()
                await session.refresh(profile)
                result["profile"] = {"id": profile.id, "name": profile.name}
        return result

    # --- Pipeline Execution ---

    async def run_pipeline(
        self,
        topic_id: str,
        profile_id: Optional[str] = None,
        subtopic_ids: Optional[list[str]] = None,
        num_research_agents: int = 3,
        num_histories: int = 2,
    ) -> dict:
        """Run the full research → compile → write pipeline for a topic."""
        profile = None
        if profile_id:
            async with async_session() as session:
                profile = await session.get(Profile, profile_id)

        # Load selected subtopics or all "todo"/"selected" ones
        async with async_session() as session:
            if subtopic_ids:
                stmt = select(Subtopic).where(Subtopic.id.in_(subtopic_ids))
            else:
                stmt = select(Subtopic).where(
                    Subtopic.topic_id == topic_id,
                    Subtopic.status.in_(["todo", "selected"]),
                )
            # Mark as selected
            for sub in (await session.execute(stmt)).scalars().all():
                sub.status = "selected"
            await session.commit()
            subtopics = (await session.execute(
                select(Subtopic).where(Subtopic.topic_id == topic_id, Subtopic.status == "selected")
            )).scalars().all()

        # Update topic status
        async with async_session() as session:
            topic = await session.get(Topic, topic_id)
            if topic:
                topic.status = "researching"
                await session.commit()

        # Phase 1: Research — spawn N research agents per subtopic
        all_sources = []
        agents = [self.research_agent_factory(f"researcher-{i+1}") for i in range(num_research_agents)]

        research_tasks = []
        for sub in subtopics:
            for agent in agents:
                research_tasks.append(agent.research(sub.title, sub.description or ""))

        research_results = await asyncio.gather(*research_tasks, return_exceptions=True)

        # Save sources to DB
        async with async_session() as session:
            for sub_idx, sub in enumerate(subtopics):
                for agent_idx in range(num_research_agents):
                    task_idx = sub_idx * num_research_agents + agent_idx
                    if task_idx < len(research_results) and not isinstance(research_results[task_idx], Exception):
                        for src in research_results[task_idx]:
                            rs = ResearchSource(
                                subtopic_id=sub.id,
                                agent_name=src["agent_name"],
                                url=src["url"],
                                title=src["title"],
                                content_snippet=src["content_snippet"][:500] if src["content_snippet"] else "",
                            )
                            session.add(rs)
                            all_sources.append(src)
            await session.commit()

        # Update topic status
        async with async_session() as session:
            topic = await session.get(Topic, topic_id)
            if topic:
                topic.status = "compiling"
                await session.commit()

        # Phase 2: Compile — create outlines per subtopic
        tone = profile.tone if profile else "neutral"
        audience = profile.audience if profile else "general"
        compiled_outlines = {}
        for sub in subtopics:
            sub_sources = [s for s in all_sources if sub.title.lower() in s.get("title", "").lower() or any(
                kw in s.get("content_snippet", "").lower() for kw in sub.title.lower().split()
            )]
            if not sub_sources:
                sub_sources = all_sources[:3]
            try:
                outline = await self.compiler.compile(sub.title, sub_sources, tone, audience)
                compiled_outlines[sub.id] = outline
            except Exception as e:
                compiled_outlines[sub.id] = {"title": sub.title, "sections": [{"heading": "Overview", "key_points": [str(e)]}]}

        # Update topic status
        async with async_session() as session:
            topic = await session.get(Topic, topic_id)
            if topic:
                topic.status = "writing"
                await session.commit()

        # Phase 3: Write — generate histories
        created_histories = []
        selected_subtopics = list(subtopics)[:num_histories] if len(subtopics) > num_histories else list(subtopics)
        style_notes = profile.style_notes if profile else ""
        preferred_length = profile.preferred_length if profile else "medium"

        for sub in selected_subtopics:
            sub_sources = [s for s in all_sources if sub.title.lower() in s.get("title", "").lower() or any(
                kw in s.get("content_snippet", "").lower() for kw in sub.title.lower().split()
            )]
            if not sub_sources:
                sub_sources = all_sources[:3]
            outline = compiled_outlines.get(sub.id, {})
            try:
                content = await self.writer.write(
                    sub.title, outline, sub_sources, tone, audience, preferred_length, style_notes
                )
            except Exception as e:
                content = f"# {sub.title}\n\n*Error during generation: {e}*\n\nPlease try again or adjust the profile."
                outline = {"title": sub.title}

            async with async_session() as session:
                history = History(
                    topic_id=topic_id,
                    subtopic_id=sub.id,
                    title=outline.get("title", sub.title),
                    content=content,
                    status="in_review",
                    profile_id=profile_id,
                )
                session.add(history)
                await session.commit()
                await session.refresh(history)
                created_histories.append({"id": history.id, "title": history.title})

        # Mark subtopics done
        async with async_session() as session:
            for sub in selected_subtopics:
                sub_obj = await session.get(Subtopic, sub.id)
                if sub_obj:
                    sub_obj.status = "done"
            topic = await session.get(Topic, topic_id)
            if topic:
                topic.status = "histories_created"
                await session.commit()

        # Send push notification
        try:
            await self.notifier.broadcast(
                "Histories Ready!",
                f"{len(created_histories)} histories ready for review.",
                f"/kanban/{topic_id}",
            )
        except Exception:
            pass

        return {"topic_id": topic_id, "histories": created_histories, "sources_count": len(all_sources)}

    # --- Feedback & Refinement ---

    async def submit_feedback(self, history_id: str, feedback_type: str, feedback_text: Optional[str] = None) -> dict:
        async with async_session() as session:
            history = await session.get(History, history_id)
            if not history:
                return {"error": "History not found"}

            record = FeedbackRecord(
                history_id=history_id,
                profile_id=history.profile_id,
                feedback_type=feedback_type,
                feedback_text=feedback_text,
            )
            session.add(record)

            if feedback_type == "accept":
                history.status = "accepted"
            elif feedback_type == "reject":
                history.status = "rejected"
            elif feedback_type == "refine_request" and feedback_text:
                history.status = "refining"
                # Get sources for refinement
                result = await session.execute(
                    select(ResearchSource).where(ResearchSource.subtopic_id == history.subtopic_id).limit(5)
                )
                sources = [{"title": s.title, "content_snippet": s.content_snippet} for s in result.scalars().all()]
                try:
                    new_content = await self.editor.refine(history.content, feedback_text, "neutral")
                    history.content = new_content
                    history.status = "in_review"
                except Exception:
                    history.status = "refining"

            history.feedback_count = (history.feedback_count or 0) + 1
            await session.commit()
            return {"history_id": history_id, "status": history.status, "feedback_type": feedback_type}

    # --- Taxonomy Learning (Profile Feedback) ---

    async def apply_profile_feedback(self, profile_id: str, feedback_type: str, feedback_text: str):
        """Store feedback on a profile for later learning."""
        async with async_session() as session:
            record = FeedbackRecord(profile_id=profile_id, feedback_type=feedback_type, feedback_text=feedback_text)
            session.add(record)
            await session.commit()
