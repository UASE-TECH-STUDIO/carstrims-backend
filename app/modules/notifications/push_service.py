"""
Web Push Notification Service using pywebpush.
Generate VAPID keys once:
    pip install py-vapid
    vapid --gen
    # Copy the public and private keys to .env
"""
import json
from datetime import datetime
from app.database.connection import get_db
from app.config.settings import settings


async def send_web_push_to_user(user_id: str, title: str, body: str, url: str = "/", icon: str = "/icon-192.png"):
    """Send a Web Push notification to all subscriptions for a user."""
    db = get_db()
    subs = await db["push_subscriptions"].find({"userId": user_id}).to_list(10)
    if not subs:
        return 0

    vapid_private = getattr(settings, "VAPID_PRIVATE_KEY", "")
    vapid_claims = {"sub": f"mailto:{getattr(settings, 'FROM_EMAIL', 'support@carstrims.com')}"}

    sent = 0
    for sub_doc in subs:
        sub = sub_doc.get("subscription", sub_doc)
        try:
            from pywebpush import webpush, WebPushException
            webpush(
                subscription_info=sub,
                data=json.dumps({
                    "title": title,
                    "body": body,
                    "url": url,
                    "icon": icon,
                    "badge": "/icon-72.png",
                    "tag": f"carstrims-{user_id}",
                    "vibrate": [200, 100, 200],
                }),
                vapid_private_key=vapid_private,
                vapid_claims=vapid_claims,
            )
            sent += 1
        except Exception as e:
            err_str = str(e)
            # Remove expired/invalid subscriptions
            if "410" in err_str or "404" in err_str:
                await db["push_subscriptions"].delete_one({"_id": sub_doc["_id"]})
            print(f"[WebPush] Error for user {user_id}: {e}")
    return sent


async def send_push_notification(
    receiver_id: str,
    title: str,
    message: str,
    url: str = "/",
    save_to_db: bool = True,
):
    """Save notification to DB and send Web Push."""
    db = get_db()
    if save_to_db:
        await db["notifications"].insert_one({
            "receiverId": receiver_id,
            "type": "general",
            "title": title,
            "message": message,
            "isRead": False,
            "data": {"url": url},
            "createdAt": datetime.utcnow(),
        })
    # Fire web push (non-blocking)
    try:
        await send_web_push_to_user(receiver_id, title, message, url)
    except Exception as e:
        print(f"[Push] Failed: {e}")
