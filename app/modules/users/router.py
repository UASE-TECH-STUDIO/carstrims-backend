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
    bio: Optional[str] = None
    instagram: Optional[str] = None
    facebook: Optional[str] = None
    twitter: Optional[str] = None
    tiktok: Optional[str] = None
    website: Optional[str] = None
    profilePicture: Optional[str] = None


router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    s = serialize_doc(current_user)
    s.pop("passwordHash", None)
    return s


@router.patch("/me")
async def update_me(data: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    update = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    update["updatedAt"] = datetime.utcnow()
    await db["users"].update_one({"_id": ObjectId(str(current_user["_id"]))}, {"$set": update})
    updated = await db["users"].find_one({"_id": ObjectId(str(current_user["_id"]))})
    s = serialize_doc(updated)
    s.pop("passwordHash", None)
    return s


@router.get("/profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    s = serialize_doc(current_user)
    s.pop("passwordHash", None)
    return s


@router.patch("/profile")
async def update_profile(data: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    update = {k: v for k, v in data.model_dump(exclude_none=True).items()}
    update["updatedAt"] = datetime.utcnow()
    await db["users"].update_one({"_id": ObjectId(str(current_user["_id"]))}, {"$set": update})
    updated = await db["users"].find_one({"_id": ObjectId(str(current_user["_id"]))})
    s = serialize_doc(updated)
    s.pop("passwordHash", None)
    return s


# ── FAVORITES — unified "favorites" collection ────────────────
@router.get("/favorites")
async def get_favorites(current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])
    # Try both collections (migration safety)
    favs = await db["favorites"].find({"userId": uid}).sort("createdAt", -1).to_list(200)
    old_favs = await db["user_favorites"].find({"userId": uid}).to_list(200)
    # Merge, deduplicate by carId
    all_car_ids = {f["carId"] for f in favs}
    for f in old_favs:
        if f["carId"] not in all_car_ids:
            favs.append(f)
            all_car_ids.add(f["carId"])

    result = []
    for fav in favs:
        car = await db["car_listings"].find_one({"carId": fav["carId"]})
        if car:
            s = serialize_doc(car)
            if car.get("dealerId") and ObjectId.is_valid(car["dealerId"]):
                dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(car["dealerId"])})
                if dealer:
                    s["dealerName"]     = dealer.get("companyName")
                    s["dealerLogo"]     = dealer.get("logo")
                    s["dealerWhatsapp"] = dealer.get("whatsapp")
                    s["dealerPhone"]    = dealer.get("phone")
                    s["dealerId"]       = dealer.get("dealerId")
            result.append(s)
    return result


@router.post("/favorites/{car_id}")
async def add_favorite(car_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])
    exists = await db["favorites"].find_one({"userId": uid, "carId": car_id})
    if not exists:
        await db["favorites"].insert_one({"userId": uid, "carId": car_id, "createdAt": datetime.utcnow()})
    return {"message": "Added to favorites", "favorited": True}


@router.delete("/favorites/{car_id}")
async def remove_favorite(car_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])
    await db["favorites"].delete_one({"userId": uid, "carId": car_id})
    await db["user_favorites"].delete_one({"userId": uid, "carId": car_id})
    return {"message": "Removed from favorites", "favorited": False}


@router.get("/likes")
async def get_likes(current_user: dict = Depends(get_current_user)):
    db = get_db()
    likes = await db["car_likes"].find({"userId": str(current_user["_id"])}).to_list(200)
    return [l["carId"] for l in likes]


# ── REQUESTS ──────────────────────────────────────────────────
@router.get("/requests")
async def get_requests(current_user: dict = Depends(get_current_user)):
    db = get_db()
    reqs = await db["car_requests"].find({"userId": str(current_user["_id"])}).sort("createdAt", -1).to_list(50)
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
    dealer_id = None; dealer_name = None
    if data.dealerId:
        dealer = await db["dealer_organizations"].find_one(
            {"_id": ObjectId(data.dealerId)} if ObjectId.is_valid(data.dealerId) else {"dealerId": data.dealerId}
        )
        if dealer:
            dealer_id = str(dealer["_id"]); dealer_name = dealer.get("companyName")
    doc = {
        "requestId": gen_id("REQ"), "userId": uid,
        "userName": current_user.get("fullName"), "userPhone": current_user.get("phone"),
        "carBrand": data.carBrand, "carModel": data.carModel, "carYear": data.carYear,
        "carColor": data.carColor, "budget": data.budget, "paymentType": data.paymentType,
        "description": data.description, "dealerId": dealer_id, "dealerName": dealer_name,
        "status": "pending", "dealerResponse": None,
        "createdAt": datetime.utcnow(), "updatedAt": datetime.utcnow(),
    }
    await db["car_requests"].insert_one(doc)
    return serialize_doc(doc)


# ── APPOINTMENTS ──────────────────────────────────────────────
@router.get("/appointments")
async def get_appointments(current_user: dict = Depends(get_current_user)):
    db = get_db()
    apts = await db["appointments"].find({"userId": str(current_user["_id"])}).sort("scheduledAt", -1).to_list(50)
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
    dealer = await db["dealer_organizations"].find_one(
        {"_id": ObjectId(data.dealerId)} if ObjectId.is_valid(data.dealerId) else {"dealerId": data.dealerId}
    )
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")
    scheduled_dt = None
    if data.scheduledAt:
        try:
            clean = data.scheduledAt.replace("T"," ").split(".")[0].split("+")[0].strip()
            scheduled_dt = datetime.fromisoformat(clean)
        except Exception: pass
    doc = {
        "appointmentId": gen_id("APT"), "userId": uid,
        "userName": current_user.get("fullName"), "userPhone": current_user.get("phone"),
        "dealerId": str(dealer["_id"]), "dealerName": dealer.get("companyName"),
        "type": data.type, "scheduledAt": scheduled_dt, "notes": data.notes,
        "status": "pending", "createdAt": datetime.utcnow(), "updatedAt": datetime.utcnow(),
    }
    await db["appointments"].insert_one(doc)
    if dealer.get("userId"):
        await db["notifications"].insert_one({
            "receiverId": dealer["userId"], "senderId": uid, "type": "appointment",
            "title": "New Appointment Request",
            "message": f"{current_user.get('fullName','A user')} wants to schedule a {data.type.replace('_',' ')}",
            "isRead": False, "createdAt": datetime.utcnow(),
        })
    return serialize_doc(doc)
