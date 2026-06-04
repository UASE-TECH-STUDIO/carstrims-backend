"""
CARSTRIMS Web Push Notification Service
Uses pywebpush with VAPID keys for push to any device/browser.
"""
import json
import asyncio
from datetime import datetime
from app.database.connection import get_db
from app.config.settings import settings


def _send_push_sync(subscription_info: dict, payload: str, vapid_private_key: str, vapid_claims: dict):
    """Synchronous pywebpush call - runs in thread pool to avoid blocking event loop."""
    from pywebpush import webpush, WebPushException
    webpush(
        subscription_info=subscription_info,
        data=payload,
        vapid_private_key=vapid_private_key,
        vapid_claims=vapid_claims,
        ttl=86400,  # 24 hours
    )


async def send_web_push_to_user(
    user_id: str,
    title: str,
    body: str,
    url: str = "/dashboard",
    icon: str = "/icon-192.png",
):
    """Send Web Push notification to ALL subscribed devices for a user."""
    if not user_id:
        return 0

    vapid_private = getattr(settings, "VAPID_PRIVATE_KEY", "").strip()
    if not vapid_private:
        print("[WebPush] VAPID_PRIVATE_KEY not set - cannot send push notifications")
        return 0

    db = get_db()
    subs = await db["push_subscriptions"].find({"userId": user_id}).to_list(20)
    if not subs:
        return 0

    vapid_claims = {
        "sub": "mailto:support@carstrims.com",
        "aud": "",  # will be set per subscription
    }

    payload = json.dumps({
        "title":   title,
        "message": body,
        "body":    body,
        "url":     url,
        "icon":    icon,
        "badge":   "/icon-72.png",
        "sound":   True,
        "tag":     f"carstrims-{user_id}-{title[:10]}",
        "vibrate": [200, 100, 200],
        "requireInteraction": False,
    })

    sent = 0
    loop = asyncio.get_event_loop()

    for sub_doc in subs:
        sub_info = sub_doc.get("subscription", sub_doc)

        # Make sure it has required fields
        endpoint  = sub_info.get("endpoint", "")
        keys      = sub_info.get("keys", {})
        if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
            print(f"[WebPush] Invalid subscription for user {user_id}")
            continue

        # Build clean subscription info
        clean_sub = {
            "endpoint": endpoint,
            "keys": {
                "p256dh": keys.get("p256dh"),
                "auth":   keys.get("auth"),
            },
        }

        # Audience must match subscription endpoint origin
        try:
            from urllib.parse import urlparse
            parsed   = urlparse(endpoint)
            audience = f"{parsed.scheme}://{parsed.netloc}"
            claims   = {"sub": "mailto:support@carstrims.com", "aud": audience}
        except Exception:
            claims = {"sub": "mailto:support@carstrims.com"}

        try:
            # Run synchronous webpush in a thread pool
            await loop.run_in_executor(
                None,
                _send_push_sync,
                clean_sub,
                payload,
                vapid_private,
                claims,
            )
            sent += 1
            print(f"[WebPush] Sent to user {user_id} at {endpoint[:50]}...")
        except Exception as e:
            err_str = str(e)
            print(f"[WebPush] Error for user {user_id}: {err_str[:200]}")
            # Remove expired/invalid subscriptions
            if "410" in err_str or "404" in err_str:
                await db["push_subscriptions"].delete_one({"_id": sub_doc["_id"]})
                print(f"[WebPush] Removed expired subscription for user {user_id}")

    print(f"[WebPush] Sent {sent}/{len(subs)} push(es) to user {user_id} - '{title}'")
    return sent


async def send_push_notification(
    receiver_id: str,
    title: str,
    message: str,
    url: str = "/dashboard",
    save_to_db: bool = True,
):
    """Save notification to DB and fire Web Push."""
    if not receiver_id:
        return 0

    db = get_db()
    if save_to_db:
        await db["notifications"].insert_one({
            "receiverId": receiver_id,
            "type":       "general",
            "title":      title,
            "message":    message,
            "isRead":     False,
            "data":       {"url": url},
            "createdAt":  datetime.utcnow(),
        })

    return await send_web_push_to_user(receiver_id, title, message, url)
