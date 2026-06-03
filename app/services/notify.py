"""
CARSTRIMS Unified Notification Service
Every notification goes through this - saves to DB AND fires push.
"""
from datetime import datetime
from app.database.connection import get_db


async def notify(
    receiver_id: str,
    title: str,
    message: str,
    notif_type: str = "general",
    sender_id: str = "",
    data: dict = None,
    url: str = "/dashboard",
):
    """
    Save a notification to the database AND fire a Web Push to the receiver's devices.
    This is the single point for ALL notifications in the app.
    """
    if not receiver_id:
        return

    db = get_db()

    doc = {
        "receiverId": receiver_id,
        "senderId":   sender_id or "",
        "type":       notif_type,
        "title":      title,
        "message":    message,
        "isRead":     False,
        "data":       data or {"url": url},
        "createdAt":  datetime.utcnow(),
    }

    await db["notifications"].insert_one(doc)

    # Fire push notification (non-blocking)
    try:
        import asyncio
        from app.modules.notifications.push_service import send_web_push_to_user
        asyncio.create_task(
            send_web_push_to_user(receiver_id, title, message, url)
        )
    except Exception as e:
        print(f"[Push] notify() push failed for {receiver_id}: {e}")
