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

# --- APPOINTMENT ENDPOINTS ---------------------------------------------------

@router.get("/me/appointments")
async def get_dealer_appointments(
    status: str = None,
    current_user: dict = Depends(get_current_dealer),
):
    """Get all appointments for this dealer, with full buyer info."""
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    dealer_id = str(dealer["_id"])

    query: dict = {"dealerId": dealer_id}
    if status and status != "all":
        query["status"] = status

    apts = await db["appointments"].find(query).sort("createdAt", -1).to_list(200)
    result = []
    for a in apts:
        s = serialize_doc(a)
        # Enrich with buyer user info
        if a.get("userId") and ObjectId.is_valid(str(a["userId"])):
            buyer = await db["users"].find_one({"_id": ObjectId(a["userId"])})
            if buyer:
                s["buyerName"] = buyer.get("fullName") or a.get("userName")
                s["buyerPhone"] = buyer.get("phone") or a.get("userPhone")
                s["buyerWhatsapp"] = buyer.get("whatsapp")
                s["buyerEmail"] = buyer.get("email")
                s["buyerAvatar"] = buyer.get("avatar") or buyer.get("profilePicture")
                s["buyerUserId"] = str(buyer["_id"])
        result.append(s)
    return result


@router.patch("/appointments/{apt_id}")
async def update_appointment(
    apt_id: str,
    data: dict = Body({}),
    current_user: dict = Depends(get_current_dealer),
):
    """
    Dealer can:
      - set status: confirmed | cancelled | completed
      - set counterProposal: { scheduledAt, note } to suggest a different time
    Buyer is notified of any change.
    """
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    # Find appointment
    apt = None
    if ObjectId.is_valid(apt_id):
        apt = await db["appointments"].find_one({
            "_id": ObjectId(apt_id), "dealerId": str(dealer["_id"])
        })
    if not apt:
        apt = await db["appointments"].find_one({
            "appointmentId": apt_id, "dealerId": str(dealer["_id"])
        })

    if not apt:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Appointment not found")

    update_fields: dict = {"updatedAt": datetime.utcnow()}

    new_status = data.get("status")
    if new_status in ("confirmed", "cancelled", "completed", "pending"):
        update_fields["status"] = new_status

    # Counter-proposal (dealer suggests alternate time)
    counter = data.get("counterProposal")
    if counter:
        cp_dt = None
        if counter.get("scheduledAt"):
            try:
                clean = str(counter["scheduledAt"]).replace("T", " ").split(".")[0].split("+")[0].strip()
                cp_dt = datetime.fromisoformat(clean)
            except Exception:
                pass
        update_fields["counterProposal"] = {
            "scheduledAt": cp_dt,
            "note": counter.get("note", ""),
            "proposedAt": datetime.utcnow(),
        }
        # Also set status to pending so buyer sees it needs re-confirmation
        update_fields["status"] = "pending_buyer"

    dealer_note = data.get("dealerNote")
    if dealer_note is not None:
        update_fields["dealerNote"] = dealer_note

    await db["appointments"].update_one(
        {"_id": apt["_id"]}, {"$set": update_fields}
    )

    # Notify the buyer
    notif_msgs = {
        "confirmed": (
            "Appointment Confirmed",
            f"Your appointment with {dealer.get('companyName')} has been confirmed!",
        ),
        "cancelled": (
            "Appointment Declined",
            f"Your appointment request with {dealer.get('companyName')} was declined.",
        ),
        "completed": (
            "Appointment Completed",
            f"Your appointment with {dealer.get('companyName')} has been marked as completed.",
        ),
        "pending_buyer": (
            "Dealer Proposed a New Time",
            f"{dealer.get('companyName')} has suggested an alternative time for your appointment.",
        ),
    }

    notif_key = update_fields.get("status", new_status)
    if notif_key and notif_key in notif_msgs and apt.get("userId"):
        title, message = notif_msgs[notif_key]
        await db["notifications"].insert_one({
            "receiverId": str(apt["userId"]),
            "senderId": str(current_user["_id"]),
            "type": "appointment",
            "title": title,
            "message": message,
            "isRead": False,
            "createdAt": datetime.utcnow(),
            "data": {"appointmentId": str(apt.get("appointmentId", apt["_id"]))},
        })

    return {"message": "Appointment updated", "status": update_fields.get("status")}


@router.post("/appointments/{apt_id}/accept-counter")
async def buyer_accept_counter(
    apt_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Buyer accepts the dealer's counter-proposed time."""
    db = get_db()
    uid = str(current_user["_id"])

    apt = None
    if ObjectId.is_valid(apt_id):
        apt = await db["appointments"].find_one({"_id": ObjectId(apt_id), "userId": uid})
    if not apt:
        apt = await db["appointments"].find_one({"appointmentId": apt_id, "userId": uid})
    if not apt:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Appointment not found")

    counter = apt.get("counterProposal", {})
    update = {
        "status": "confirmed",
        "updatedAt": datetime.utcnow(),
    }
    if counter.get("scheduledAt"):
        update["scheduledAt"] = counter["scheduledAt"]
        update["counterProposal"] = None  # clear it once accepted

    await db["appointments"].update_one({"_id": apt["_id"]}, {"$set": update})

    # Notify dealer
    if apt.get("dealerId") and ObjectId.is_valid(str(apt["dealerId"])):
        dealer_doc = await db["dealer_organizations"].find_one({"_id": ObjectId(apt["dealerId"])})
        if dealer_doc and dealer_doc.get("userId"):
            await db["notifications"].insert_one({
                "receiverId": str(dealer_doc["userId"]),
                "senderId": uid,
                "type": "appointment",
                "title": "Buyer Accepted New Time",
                "message": f"{current_user.get('fullName', 'Buyer')} accepted your proposed appointment time.",
                "isRead": False,
                "createdAt": datetime.utcnow(),
            })

    return {"message": "Appointment confirmed with new time"}


@router.post("/appointments/{apt_id}/cancel")
async def buyer_cancel_appointment(
    apt_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Buyer cancels their own appointment."""
    db = get_db()
    uid = str(current_user["_id"])

    apt = None
    if ObjectId.is_valid(apt_id):
        apt = await db["appointments"].find_one({"_id": ObjectId(apt_id), "userId": uid})
    if not apt:
        apt = await db["appointments"].find_one({"appointmentId": apt_id, "userId": uid})
    if not apt:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Appointment not found")

    await db["appointments"].update_one(
        {"_id": apt["_id"]},
        {"$set": {"status": "cancelled_by_buyer", "updatedAt": datetime.utcnow()}}
    )

    # Notify dealer
    if apt.get("dealerId") and ObjectId.is_valid(str(apt["dealerId"])):
        dealer_doc = await db["dealer_organizations"].find_one({"_id": ObjectId(apt["dealerId"])})
        if dealer_doc and dealer_doc.get("userId"):
            await db["notifications"].insert_one({
                "receiverId": str(dealer_doc["userId"]),
                "senderId": uid,
                "type": "appointment",
                "title": "Appointment Cancelled",
                "message": f"{apt.get('userName', 'A buyer')} cancelled their appointment.",
                "isRead": False,
                "createdAt": datetime.utcnow(),
            })

    return {"message": "Appointment cancelled"}