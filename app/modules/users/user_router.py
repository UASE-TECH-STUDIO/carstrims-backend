from fastapi import APIRouter, Depends, Query, Body
from typing import Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_user
from app.modules.dealers.service import serialize_doc
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime
import random, string


def gen_id(prefix: str) -> str:
    return f"{prefix}-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


class AppointmentCreate(BaseModel):
    dealerId: str
    type: str = "showroom_visit"
    scheduledAt: Optional[str] = None
    notes: Optional[str] = None


class RequestCreate(BaseModel):
    carBrand: str
    carModel: str
    carYear: Optional[int] = None
    carColor: Optional[str] = None
    budget: Optional[float] = None
    paymentType: str = "full"
    description: Optional[str] = None
    dealerId: Optional[str] = None


class ProfileUpdate(BaseModel):
    fullName: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    profilePicture: Optional[str] = None


router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.get("/profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    return serialize_doc(current_user)


@router.patch("/profile")
async def update_profile(
    data: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    update = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    update["updatedAt"] = datetime.utcnow()
    await db["users"].update_one(
        {"_id": ObjectId(str(current_user["_id"]))},
        {"$set": update},
    )
    updated = await db["users"].find_one({"_id": ObjectId(str(current_user["_id"]))})
    return serialize_doc(updated)


# ── FAVORITES ────────────────────────────────────────────────────────────────

@router.get("/favorites")
async def get_favorites(current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])
    favs = await db["user_favorites"].find({"userId": uid}).to_list(100)
    result = []
    for fav in favs:
        car = await db["car_listings"].find_one({"carId": fav["carId"]})
        if car:
            s = serialize_doc(car)
            if car.get("dealerId") and ObjectId.is_valid(car["dealerId"]):
                dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(car["dealerId"])})
                if dealer:
                    s["dealerName"] = dealer.get("companyName")
                    s["dealerLogo"] = dealer.get("logo")
                    s["dealerWhatsapp"] = dealer.get("whatsapp")
                    s["dealerPhone"] = dealer.get("phone")
            result.append(s)
    return result


@router.post("/favorites/{car_id}")
async def add_favorite(car_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])
    exists = await db["user_favorites"].find_one({"userId": uid, "carId": car_id})
    if not exists:
        await db["user_favorites"].insert_one({"userId": uid, "carId": car_id, "createdAt": datetime.utcnow()})
    return {"message": "Added to favorites"}


@router.delete("/favorites/{car_id}")
async def remove_favorite(car_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    await db["user_favorites"].delete_one({"userId": str(current_user["_id"]), "carId": car_id})
    return {"message": "Removed from favorites"}


@router.get("/likes")
async def get_likes(current_user: dict = Depends(get_current_user)):
    db = get_db()
    likes = await db["car_likes"].find({"userId": str(current_user["_id"])}).to_list(200)
    return [l["carId"] for l in likes]


# ── REQUESTS ─────────────────────────────────────────────────────────────────

@router.get("/requests")
async def get_requests(current_user: dict = Depends(get_current_user)):
    db = get_db()
    reqs = await db["car_requests"].find(
        {"userId": str(current_user["_id"])}
    ).sort("createdAt", -1).to_list(50)
    result = []
    for r in reqs:
        s = serialize_doc(r)
        if r.get("dealerId") and ObjectId.is_valid(r["dealerId"]):
            dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(r["dealerId"])})
            if dealer:
                s["dealerName"] = dealer.get("companyName")
                s["dealerPhone"] = dealer.get("phone")
        result.append(s)
    return result


@router.post("/requests")
async def create_request(data: RequestCreate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])

    dealer_id = None
    dealer_name = None
    if data.dealerId:
        if ObjectId.is_valid(data.dealerId):
            dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(data.dealerId)})
        else:
            dealer = await db["dealer_organizations"].find_one({"dealerId": data.dealerId})
        if dealer:
            dealer_id = str(dealer["_id"])
            dealer_name = dealer.get("companyName")

    doc = {
        "requestId": gen_id("REQ"),
        "userId": uid,
        "userName": current_user.get("fullName"),
        "userPhone": current_user.get("phone"),
        "carBrand": data.carBrand,
        "carModel": data.carModel,
        "carYear": data.carYear,
        "carColor": data.carColor,
        "budget": data.budget,
        "paymentType": data.paymentType,
        "description": data.description,
        "dealerId": dealer_id,
        "dealerName": dealer_name,
        "status": "pending",
        "dealerResponse": None,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }
    await db["car_requests"].insert_one(doc)

    # Notify dealer(s)
    if dealer_id:
        dealer_obj = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
        if dealer_obj:
            await db["notifications"].insert_one({
                "receiverId": dealer_obj.get("userId"),
                "senderId": uid,
                "type": "car_request",
                "title": "New Car Request",
                "message": f"{current_user.get('fullName','A user')} is looking for {data.carBrand} {data.carModel}",
                "isRead": False,
                "data": {"requestId": doc["requestId"]},
                "createdAt": datetime.utcnow(),
            })

    return serialize_doc(doc)


@router.post("/requests/{request_id}/accept")
async def accept_request(request_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    await db["car_requests"].update_one(
        {"requestId": request_id, "userId": str(current_user["_id"])},
        {"$set": {"status": "accepted", "updatedAt": datetime.utcnow()}},
    )
    return {"message": "Request accepted"}


@router.post("/requests/{request_id}/reject")
async def reject_request(request_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    await db["car_requests"].update_one(
        {"requestId": request_id, "userId": str(current_user["_id"])},
        {"$set": {"status": "rejected_by_user", "updatedAt": datetime.utcnow()}},
    )
    return {"message": "Rejected"}


# ── APPOINTMENTS ─────────────────────────────────────────────────────────────

@router.get("/appointments")
async def get_appointments(current_user: dict = Depends(get_current_user)):
    db = get_db()
    apts = await db["appointments"].find(
        {"userId": str(current_user["_id"])}
    ).sort("scheduledAt", -1).to_list(50)
    result = []
    for a in apts:
        s = serialize_doc(a)
        if a.get("dealerId") and ObjectId.is_valid(a["dealerId"]):
            dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(a["dealerId"])})
            if dealer:
                s["dealerName"] = dealer.get("companyName")
                s["dealerPhone"] = dealer.get("phone")
                s["dealerWhatsapp"] = dealer.get("whatsapp")
        result.append(s)
    return result


@router.post("/appointments")
async def create_appointment(data: AppointmentCreate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])

    # Accept both ObjectId and dealerId string
    if ObjectId.is_valid(data.dealerId):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(data.dealerId)})
    else:
        dealer = await db["dealer_organizations"].find_one({"dealerId": data.dealerId})

    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")

    scheduled_dt = None
    if data.scheduledAt:
        try:
            # Handle ISO format with or without timezone
            clean = data.scheduledAt.replace("T", " ").split(".")[0].split("+")[0].strip()
            scheduled_dt = datetime.fromisoformat(clean)
        except Exception:
            scheduled_dt = None

    doc = {
        "appointmentId": gen_id("APT"),
        "userId": uid,
        "userName": current_user.get("fullName"),
        "userPhone": current_user.get("phone"),
        "dealerId": str(dealer["_id"]),
        "dealerName": dealer.get("companyName"),
        "type": data.type,
        "scheduledAt": scheduled_dt,
        "notes": data.notes,
        "status": "pending",
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }
    await db["appointments"].insert_one(doc)

    # Notify dealer
    if dealer.get("userId"):
        await db["notifications"].insert_one({
            "receiverId": dealer["userId"],
            "senderId": uid,
            "type": "appointment",
            "title": "New Appointment Request",
            "message": f"{current_user.get('fullName','A user')} wants to schedule a {data.type.replace('_',' ')}",
            "isRead": False,
            "data": {"appointmentId": doc["appointmentId"]},
            "createdAt": datetime.utcnow(),
        })

    return serialize_doc(doc)