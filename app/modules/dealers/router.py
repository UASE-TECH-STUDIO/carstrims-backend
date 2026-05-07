from fastapi import APIRouter, Depends, Query, Body
from typing import Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_user, get_current_dealer
from app.modules.dealers.service import (
    create_dealer_profile, get_dealer_by_user_id,
    update_dealer_profile, get_dealer_stats, serialize_doc,
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
async def setup_dealer(data: DealerSetupRequest, current_user: dict = Depends(get_current_dealer)):
    return await create_dealer_profile(str(current_user["_id"]), data.model_dump())


@router.get("/me")
async def get_my_dealer(current_user: dict = Depends(get_current_dealer)):
    return await get_dealer_by_user_id(str(current_user["_id"]))


@router.patch("/me")
async def update_my_dealer(data: dict = Body(...), current_user: dict = Depends(get_current_dealer)):
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


@router.get("/me/appointments")
async def my_appointments(current_user: dict = Depends(get_current_dealer)):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    apts = await db["appointments"].find(
        {"dealerId": dealer["_id"]}
    ).sort("scheduledAt", -1).to_list(100)
    result = []
    for a in apts:
        s = serialize_doc(a)
        if a.get("userId") and ObjectId.is_valid(a["userId"]):
            user = await db["users"].find_one({"_id": ObjectId(a["userId"])})
            s["userName"] = user.get("fullName") if user else "—"
            s["userPhone"] = user.get("phone") if user else "—"
        result.append(s)
    return result


@router.patch("/appointments/:apt_id")
async def update_appointment(
    apt_id: str,
    data: dict = Body(...),
    current_user: dict = Depends(get_current_dealer),
):
    db = get_db()
    await db["appointments"].update_one(
        {"$or": [
            {"appointmentId": apt_id},
            {"_id": ObjectId(apt_id) if ObjectId.is_valid(apt_id) else apt_id},
        ]},
        {"$set": {"status": data.get("status"), "updatedAt": datetime.utcnow()}},
    )
    return {"message": "Updated"}


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
