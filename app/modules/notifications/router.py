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

@router.get("/dealer-notifications")
async def get_dealer_notifications(
    skip: int = Query(0),
    limit: int = Query(50),
    current_user: dict = Depends(get_current_user),
):
    """
    Returns the DEALER's notifications - for staff to see and help manage.
    Staff with message/manage permissions can view dealer notifications.
    """
    db = get_db()
    uid = str(current_user["_id"])
    role = current_user.get("role")

    # Only staff can use this endpoint
    if role != "DEALER_STAFF":
        from fastapi import HTTPException
        raise HTTPException(403, "Staff access only")

    # Find staff account to get dealer's userId
    staff = await db["staff_accounts"].find_one({"userId": uid})
    if not staff:
        return {"total": 0, "unreadCount": 0, "notifications": []}

    # Get dealer's userId
    from bson import ObjectId
    dealer_id_raw = staff.get("dealerId")
    dealer = None
    if isinstance(dealer_id_raw, ObjectId):
        dealer = await db["dealer_organizations"].find_one({"_id": dealer_id_raw})
    elif dealer_id_raw and ObjectId.is_valid(str(dealer_id_raw)):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(str(dealer_id_raw))})

    if not dealer:
        return {"total": 0, "unreadCount": 0, "notifications": []}

    dealer_user_id = str(dealer.get("userId", ""))
    if not dealer_user_id:
        return {"total": 0, "unreadCount": 0, "notifications": []}

    # Get dealer's notifications
    query = {"receiverId": dealer_user_id}
    total  = await db["notifications"].count_documents(query)
    unread = await db["notifications"].count_documents({**query, "isRead": False})
    notifs = await db["notifications"].find(query).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)

    return {
        "total":       total,
        "unreadCount": unread,
        "notifications": [serialize_doc(n) for n in notifs],
    }


@router.post("/dealer-read-all")
async def dealer_mark_all_read(current_user: dict = Depends(get_current_user)):
    """Staff marks all dealer notifications as read."""
    db = get_db()
    uid = str(current_user["_id"])
    if current_user.get("role") != "DEALER_STAFF":
        return {"message": "ok"}

    staff = await db["staff_accounts"].find_one({"userId": uid})
    if not staff:
        return {"message": "ok"}

    from bson import ObjectId
    did = staff.get("dealerId")
    dealer = None
    if isinstance(did, ObjectId):
        dealer = await db["dealer_organizations"].find_one({"_id": did})
    elif did and ObjectId.is_valid(str(did)):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(str(did))})

    if dealer and dealer.get("userId"):
        await db["notifications"].update_many(
            {"receiverId": str(dealer["userId"]), "isRead": False},
            {"$set": {"isRead": True}}
        )
    return {"message": "All dealer notifications marked read"}

