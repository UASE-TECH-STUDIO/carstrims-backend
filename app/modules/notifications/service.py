import httpx
import asyncio
from datetime import datetime
from app.database.connection import get_db

SOCKET_SERVER_URL = "http://localhost:3001"


async def push_notification(
    receiver_id: str,
    notification_type: str,
    title: str,
    message: str,
    sender_id: str = None,
    dealer_id: str = None,
    data: dict = None,
):
    """Save notification to DB and push via socket server"""
    db = get_db()

    # Save to MongoDB
    doc = {
        "receiverId": receiver_id,
        "senderId": sender_id,
        "dealerId": dealer_id,
        "type": notification_type,
        "title": title,
        "message": message,
        "isRead": False,
        "data": data or {},
        "createdAt": datetime.utcnow(),
    }
    await db["notifications"].insert_one(doc)

    # Push via socket server (fire and forget)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(
                f"{SOCKET_SERVER_URL}/internal/notify",
                json={
                    "userId": receiver_id,
                    "type": notification_type,
                    "title": title,
                    "message": message,
                    "data": data or {},
                },
            )
    except Exception:
        # Socket server might not be running — that's ok, DB has the notification
        pass


async def get_user_notifications(
    user_id: str,
    unread_only: bool = False,
    skip: int = 0,
    limit: int = 30,
) -> dict:
    db = get_db()
    query = {"receiverId": user_id}
    if unread_only:
        query["isRead"] = False

    total = await db["notifications"].count_documents(query)
    unread_count = await db["notifications"].count_documents(
        {"receiverId": user_id, "isRead": False}
    )

    notifications = await db["notifications"].find(query).sort(
        "createdAt", -1
    ).skip(skip).limit(limit).to_list(limit)

    from app.modules.dealers.service import serialize_doc
    return {
        "total": total,
        "unreadCount": unread_count,
        "notifications": [serialize_doc(n) for n in notifications],
    }


async def mark_notification_read(notification_id: str, user_id: str) -> dict:
    db = get_db()
    from bson import ObjectId
    await db["notifications"].update_one(
        {"_id": ObjectId(notification_id), "receiverId": user_id},
        {"$set": {"isRead": True}},
    )
    return {"message": "Marked as read"}


async def mark_all_read(user_id: str) -> dict:
    db = get_db()
    await db["notifications"].update_many(
        {"receiverId": user_id, "isRead": False},
        {"$set": {"isRead": True}},
    )
    return {"message": "All notifications marked as read"}
