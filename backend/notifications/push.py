import json
from typing import Optional
from backend.models.push_subscription import PushSubscription
from backend.database import async_session

try:
    from pywebpush import webpush, WebPushException
    HAS_PYWEBPUSH = True
except ImportError:
    HAS_PYWEBPUSH = False

from backend.config import settings

class PushNotifier:
    """Send web push notifications to subscribed clients."""

    def __init__(self):
        self.vapid_private_key = settings.vapid_private_key
        self.vapid_claim = {"sub": f"mailto:{settings.vapid_claim_email}"}

    async def send_notification(self, subscription: PushSubscription, title: str, body: str, url: str = "/"):
        """Send a push notification to a single subscriber."""
        if not HAS_PYWEBPUSH or not self.vapid_private_key:
            print(f"[PushNotifier] Skipping push (no pywebpush or VAPID key). Would send: {title} - {body}")
            return False

        try:
            sub_info = {
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            }
            payload = json.dumps({"title": title, "body": body, "url": url})
            webpush(
                subscription_info=sub_info,
                data=payload,
                vapid_private_key=self.vapid_private_key,
                vapid_claims=self.vapid_claim,
            )
            return True
        except WebPushException as e:
            if e.response and e.response.status_code in (410, 404):
                # Subscription expired or gone
                print(f"[PushNotifier] Removing expired subscription: {subscription.endpoint[:40]}...")
                async with async_session() as session:
                    await session.delete(subscription)
                    await session.commit()
            return False

    async def broadcast(self, title: str, body: str, url: str = "/"):
        """Send notification to all subscribers."""
        async with async_session() as session:
            from sqlalchemy import select
            result = await session.execute(select(PushSubscription))
            subscriptions = result.scalars().all()

        sent = 0
        for sub in subscriptions:
            if await self.send_notification(sub, title, body, url):
                sent += 1
        return sent