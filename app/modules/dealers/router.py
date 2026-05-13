# Add this to your existing dealers router (app/modules/dealers/router.py)
# Replace the existing /setup endpoint with this version.
# Key change: after dealer profile is created, user status moves from
# "pending_setup" to "awaiting_approval" so admin can see them in the approvals queue.

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_user, get_current_dealer
from app.modules.dealers.service import (
    create_dealer_profile, get_dealer_by_user_id,
    update_dealer_profile, serialize_doc,
)
from app.modules.dealers.stats_service import (
    get_dealer_stats_full, get_dealer_notifications,
    mark_notification_read, mark_all_read, get_dealer_reports,
)
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime

router = APIRouter(prefix="/api/v1/dealers", tags=["Dealers"])


class DealerSetupRequest(BaseModel):
    companyName: str
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = "Nigeria"
    description: Optional[str] = None


@router.post("/setup")
async def setup_dealer(
    data: DealerSetupRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Creates the dealer's organization profile.
    Only DEALER_ADMIN users can call this.
    After setup, user status moves from "pending_setup" to "awaiting_approval"
    so the super admin can see them in the approvals queue.
    """
    if current_user.get("role") != "DEALER_ADMIN":
        raise HTTPException(status_code=403, detail="Only dealer accounts can set up a dealership profile")

    db = get_db()
    uid = str(current_user["_id"])

    # Prevent duplicate setup
    existing = await db["dealer_organizations"].find_one({"userId": uid})
    if existing:
        raise HTTPException(status_code=400, detail="Dealer profile already exists. Use PATCH /api/v1/dealers/me to update it.")

    # Create the dealer profile (your existing service handles this)
    result = await create_dealer_profile(uid, data.model_dump())

    # Transition user status: pending_setup -> awaiting_approval
    # This makes them visible in the admin approvals queue
    await db["users"].update_one(
        {"_id": current_user["_id"]},
        {"$set": {
            "status": "awaiting_approval",
            "updatedAt": datetime.utcnow(),
        }}
    )

    # Notify super admins that a new dealer is ready for review
    admins = await db["users"].find({"role": "SYSTEM_ADMIN"}).to_list(5)
    for admin in admins:
        await db["notifications"].insert_one({
            "receiverId": str(admin["_id"]),
            "type": "dealer_pending_approval",
            "title": "New Dealer Ready for Review",
            "message": data.companyName + " has completed their dealership setup and is awaiting your approval.",
            "isRead": False,
            "data": {"dealerUserId": uid, "companyName": data.companyName},
            "createdAt": datetime.utcnow(),
        })

    return {
        **result,
        "message": "Dealership profile created. Your account is now pending approval from the CARSTRIMS admin team.",
        "status": "awaiting_approval",
    }


@router.get("/me")
async def get_my_dealer(current_user: dict = Depends(get_current_user)):
    """
    Returns the dealer profile for the current user.
    Works for both pending and approved dealers so the layout can check status.
    """
    if current_user.get("role") != "DEALER_ADMIN":
        raise HTTPException(status_code=403, detail="Dealer access required")
    db = get_db()
    uid = str(current_user["_id"])
    dealer = await db["dealer_organizations"].find_one({"userId": uid})
    if not dealer:
        raise HTTPException(status_code=404, detail="No dealer profile found")
    return serialize_doc(dealer)


@router.patch("/me")
async def update_my_dealer(
    data: dict = Body(...),
    current_user: dict = Depends(get_current_dealer),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await update_dealer_profile(dealer["_id"], data)


@router.get("/me/stats")
async def my_stats(current_user: dict = Depends(get_current_dealer)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await get_dealer_stats_full(dealer["_id"])


@router.get("/me/reports")
async def my_reports(current_user: dict = Depends(get_current_dealer)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await get_dealer_reports(dealer["_id"])


@router.get("/me/notifications")
async def my_notifications(
    skip: int = Query(0),
    limit: int = Query(50),
    current_user: dict = Depends(get_current_dealer),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await get_dealer_notifications(dealer["_id"], str(current_user["_id"]), skip, limit)


@router.post("/me/notifications/{notif_id}/read")
async def read_notification(notif_id: str, current_user: dict = Depends(get_current_dealer)):
    return await mark_notification_read(notif_id, str(current_user["_id"]))


@router.post("/me/notifications/read-all")
async def read_all_notifications(current_user: dict = Depends(get_current_dealer)):
    return await mark_all_read(str(current_user["_id"]))