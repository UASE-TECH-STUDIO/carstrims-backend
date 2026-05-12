from fastapi import APIRouter, Depends, Body
from app.auth.dependencies import get_current_user
from app.database.connection import get_db
from datetime import datetime

router = APIRouter(prefix="/api/v1/push", tags=["Push Notifications"])


@router.post("/subscribe")
async def subscribe(
    subscription: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    uid = str(current_user["_id"])
    # Upsert subscription for this user
    await db["push_subscriptions"].update_one(
        {"userId": uid, "endpoint": subscription.get("endpoint")},
        {"$set": {
            "userId": uid,
            "subscription": subscription,
            "updatedAt": datetime.utcnow(),
        }},
        upsert=True,
    )
    return {"message": "Subscribed to push notifications"}


@router.post("/unsubscribe")
async def unsubscribe(
    data: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    await db["push_subscriptions"].delete_many({
        "userId": str(current_user["_id"]),
        "endpoint": data.get("endpoint"),
    })
    return {"message": "Unsubscribed"}


@router.get("/vapid-public-key")
async def get_vapid_key():
    # In production, generate VAPID keys with: py-vapid or web-push
    # For now return a placeholder - users need to generate their own
    from app.config.settings import settings
    return {"publicKey": getattr(settings, "VAPID_PUBLIC_KEY", "")}