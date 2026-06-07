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

@router.post("/send-test")
async def send_test_push(current_user: dict = Depends(get_current_user)):
    """Send a test push notification to the current user."""
    from app.modules.notifications.push_service import send_push_notification
    uid = str(current_user["_id"])
    await send_push_notification(uid, "CARSTRIMS Test ", "Push notifications are working!", "/dashboard", save_to_db=False)
    return {"message": "Test push sent"}


@router.post("/send")
async def send_push_to_user(
    data: dict = Body(...),
    admin=Depends(get_current_user),
):
    """Send push notification to a specific user (admin or system use)."""
    from app.modules.notifications.push_service import send_push_notification
    receiver_id = data.get("userId") or data.get("receiverId")
    if not receiver_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="userId required")
    sent = await send_push_notification(
        receiver_id,
        data.get("title", "CARSTRIMS"),
        data.get("message", "You have a new notification"),
        data.get("url", "/"),
    )
    return {"sent": sent}

@router.post("/register-device")
async def register_device(
    data: dict = Body({}),
    current_user: dict = Depends(get_current_user),
):
    """Register mobile FCM device token for Android/iOS push notifications."""
    db = get_db()
    uid = str(current_user["_id"])
    token = data.get("token", "").strip()
    platform = data.get("platform", "android")

    if not token:
        raise HTTPException(status_code=400, detail="Token required")

    await db["device_tokens"].update_one(
        {"userId": uid, "token": token},
        {"$set": {
            "userId": uid,
            "token": token,
            "platform": platform,
            "updatedAt": datetime.utcnow(),
        }},
        upsert=True,
    )
    return {"message": "Device registered for push notifications"}

