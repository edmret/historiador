from fastapi import APIRouter, HTTPException
from backend.schemas.orchestrator import TopicSubmit, TopicStatusResponse
from backend.agents.orchestrator import HistoriadorOrchestrator
from backend.database import async_session
from backend.models.topic import Topic

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
orchestrator = HistoriadorOrchestrator()

@router.post("/run", response_model=dict)
async def run_pipeline(body: TopicSubmit):
    if not body.topic_title:
        raise HTTPException(400, "topic_title is required")
    topic = await orchestrator.create_topic(body.topic_title)
    result = await orchestrator.run_pipeline(
        topic_id=topic.id,
        profile_id=body.profile_id,
        subtopic_ids=body.subtopic_ids,
        num_research_agents=body.num_research_agents or 3,
        num_histories=body.num_histories or 2,
    )
    return result

@router.get("/status/{topic_id}", response_model=TopicStatusResponse)
async def get_pipeline_status(topic_id: str):
    async with async_session() as session:
        topic = await session.get(Topic, topic_id)
        if not topic:
            raise HTTPException(404, "Topic not found")
        progress_map = {
            "scoping": 0.05, "scoping_complete": 0.1,
            "researching": 0.25, "compiling": 0.5,
            "writing": 0.75, "histories_created": 0.95,
        }
        return TopicStatusResponse(
            topic_id=topic.id, title=topic.title, status=topic.status,
            progress_pct=progress_map.get(topic.status, 0.0),
            current_stage=topic.status.replace("_", " ").title(),
            created_at=topic.created_at, updated_at=topic.updated_at,
        )
