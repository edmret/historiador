from fastapi import APIRouter, HTTPException
from backend.database import async_session
from backend.models.push_subscription import PushSubscription
from backend.schemas.orchestrator import PushSubscriptionCreate

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

@router.post("/subscribe", status_code=201)
async def subscribe(body: PushSubscriptionCreate):
    async with async_session() as session:
        sub = PushSubscription(endpoint=body.endpoint, p256dh=body.p256dh, auth=body.auth)
        session.add(sub)
        await session.commit()
        return {"status": "subscribed"}

@router.post("/unsubscribe", status_code=200)
async def unsubscribe(body: PushSubscriptionCreate):
    from sqlalchemy import select
    async with async_session() as session:
        result = await session.execute(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
        sub = result.scalar_one_or_none()
        if sub:
            await session.delete(sub)
            await session.commit()
        return {"status": "unsubscribed"}
