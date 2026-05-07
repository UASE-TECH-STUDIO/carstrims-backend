from fastapi import APIRouter, Depends, Query
from typing import Optional
from app.auth.dependencies import get_current_user
from app.modules.dealers.service import serialize_doc
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


@router.get("/")
async def get_notifications(
    skip: int = Query(0),
    limit: int = Query(50),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    uid = str(current_user["_id"])
    total = await db["notifications"].count_documents({"receiverId": uid})
    unread = await db["notifications"].count_documents({"receiverId": uid, "isRead": False})
    notifs = await db["notifications"].find(
        {"receiverId": uid}
    ).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)

    return {
        "total": total,
        "unreadCount": unread,
        "notifications": [serialize_doc(n) for n in notifs],
    }


@router.post("/{notif_id}/read")
async def mark_read(notif_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])
    query = {"receiverId": uid}
    if ObjectId.is_valid(notif_id):
        query["_id"] = ObjectId(notif_id)
    else:
        query["notifId"] = notif_id
    await db["notifications"].update_one(
        query,
        {"$set": {"isRead": True, "readAt": datetime.utcnow()}},
    )
    return {"message": "Marked as read"}


@router.post("/read-all")
async def mark_all_read(current_user: dict = Depends(get_current_user)):
    db = get_db()
    await db["notifications"].update_many(
        {"receiverId": str(current_user["_id"]), "isRead": False},
        {"$set": {"isRead": True, "readAt": datetime.utcnow()}},
    )
    return {"message": "All marked as read"}
