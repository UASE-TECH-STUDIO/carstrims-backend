from fastapi import APIRouter, Depends, Query, Body
from typing import Optional
from pydantic import BaseModel, EmailStr
from app.auth.dependencies import get_current_admin
from app.modules.users.admin_service import (
    get_platform_stats, get_all_dealers_admin, get_dealer_full_profile,
    get_recent_activity, get_growth_chart, get_top_dealers,
    admin_create_dealer, admin_warn_dealer, admin_delete_dealer, admin_reset_password,
)
from app.modules.users.user_service import get_all_users_admin
from app.modules.dealers.service import (
    approve_dealer, reject_dealer, suspend_dealer,
)


class WarnRequest(BaseModel):
    note: str


class AdminCreateDealerRequest(BaseModel):
    fullName: str
    username: str
    email: EmailStr
    phone: Optional[str] = ""
    companyName: str
    address: Optional[str] = ""
    city: Optional[str] = ""
    state: Optional[str] = ""
    country: Optional[str] = "Nigeria"


class RejectRequest(BaseModel):
    reason: Optional[str] = None


router = APIRouter(prefix="/api/v1/admin", tags=["Super Admin"])


@router.get("/stats")
async def platform_stats(current_user: dict = Depends(get_current_admin)):
    return await get_platform_stats()


@router.get("/dealers")
async def list_all_dealers(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(20),
    current_user: dict = Depends(get_current_admin),
):
    return await get_all_dealers_admin(status, search, skip, limit)


@router.get("/users")
async def list_all_users(
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(20),
    current_user: dict = Depends(get_current_admin),
):
    return await get_all_users_admin(search, role, skip, limit)


@router.get("/dealers/{dealer_id}/profile")
async def dealer_full_profile(dealer_id: str, current_user: dict = Depends(get_current_admin)):
    return await get_dealer_full_profile(dealer_id)


@router.post("/dealers/{dealer_id}/approve")
async def approve(dealer_id: str, current_user: dict = Depends(get_current_admin)):
    return await approve_dealer(dealer_id, str(current_user["_id"]))


@router.post("/dealers/{dealer_id}/reject")
async def reject(dealer_id: str, data: RejectRequest, current_user: dict = Depends(get_current_admin)):
    return await reject_dealer(dealer_id, str(current_user["_id"]), data.reason)


@router.post("/dealers/{dealer_id}/suspend")
async def suspend(dealer_id: str, data: WarnRequest, current_user: dict = Depends(get_current_admin)):
    return await suspend_dealer(dealer_id, str(current_user["_id"]), data.note)


@router.post("/dealers/{dealer_id}/warn")
async def warn(dealer_id: str, data: WarnRequest, current_user: dict = Depends(get_current_admin)):
    return await admin_warn_dealer(dealer_id, data.note)


@router.delete("/dealers/{dealer_id}")
async def delete_dealer(dealer_id: str, current_user: dict = Depends(get_current_admin)):
    return await admin_delete_dealer(dealer_id)


@router.post("/dealers/{dealer_user_id}/reset-password")
async def reset_password(dealer_user_id: str, current_user: dict = Depends(get_current_admin)):
    return await admin_reset_password(dealer_user_id)


@router.post("/dealers/create")
async def create_dealer(data: AdminCreateDealerRequest, current_user: dict = Depends(get_current_admin)):
    return await admin_create_dealer(data.model_dump())


@router.get("/activity")
async def recent_activity(limit: int = Query(20), current_user: dict = Depends(get_current_admin)):
    return await get_recent_activity(limit)


@router.get("/growth")
async def growth_chart(current_user: dict = Depends(get_current_admin)):
    return await get_growth_chart()


@router.get("/top-dealers")
async def top_dealers(limit: int = Query(10), current_user: dict = Depends(get_current_admin)):
    return await get_top_dealers(limit)


@router.post("/broadcast")
async def broadcast_message(
    data: dict,
    current_user: dict = Depends(get_current_admin),
):
    from app.database.connection import get_db
    from datetime import datetime
    db = get_db()

    target_role = data.get("targetRole", "all")
    title = data.get("title", "")
    message = data.get("message", "")
    msg_type = data.get("type", "announcement")

    query = {}
    if target_role != "all":
        query["role"] = target_role

    users = await db["users"].find(query, {"_id": 1}).to_list(10000)
    user_ids = [str(u["_id"]) for u in users]

    notifications = [
        {
            "receiverId": uid,
            "senderId": str(current_user["_id"]),
            "type": msg_type,
            "title": title,
            "message": message,
            "isRead": False,
            "createdAt": datetime.utcnow(),
        }
        for uid in user_ids
    ]

    if notifications:
        await db["notifications"].insert_many(notifications)

    return {
        "message": "Broadcast sent successfully",
        "sentTo": len(user_ids),
        "targetRole": target_role,
    }
