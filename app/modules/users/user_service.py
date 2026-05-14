from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc
import random
import string


def gen_id(prefix: str) -> str:
    return prefix + "-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


# ── FAVORITES ────────────────────────────────────────────────────────────────
# IMPORTANT: both the public feed route (POST /public/cars/{id}/favorite)
# and the user dashboard route (GET /users/favorites) use this same service
# and the same MongoDB collection: "favorites"
# This is what fixes the empty favorites bug.

async def add_favorite(user_id: str, car_id: str) -> dict:
    db = get_db()
    # Accept carId string or MongoDB ObjectId
    car = None
    if ObjectId.is_valid(car_id):
        car = await db["car_listings"].find_one({"_id": ObjectId(car_id)})
        # normalize to carId string
        if car:
            car_id = car.get("carId", car_id)
    if not car:
        car = await db["car_listings"].find_one({"carId": car_id})
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    existing = await db["favorites"].find_one({"userId": user_id, "carId": car_id})
    if not existing:
        await db["favorites"].insert_one({
            "userId": user_id,
            "carId": car_id,
            "createdAt": datetime.utcnow(),
        })
    return {"message": "Added to favorites", "favorited": True}


async def remove_favorite(user_id: str, car_id: str) -> dict:
    db = get_db()
    # Accept either format
    if ObjectId.is_valid(car_id):
        car = await db["car_listings"].find_one({"_id": ObjectId(car_id)})
        if car:
            car_id = car.get("carId", car_id)
    await db["favorites"].delete_one({"userId": user_id, "carId": car_id})
    return {"message": "Removed from favorites", "favorited": False}


async def get_favorites(user_id: str) -> list:
    db = get_db()
    favs = await db["favorites"].find({"userId": user_id}).sort("createdAt", -1).to_list(200)
    result = []
    for f in favs:
        car = await db["car_listings"].find_one({"carId": f["carId"]})
        if car:
            s = serialize_doc(car)
            dealer = None
            if car.get("dealerId") and ObjectId.is_valid(car["dealerId"]):
                dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(car["dealerId"])})
            if dealer:
                s["dealerName"]     = dealer.get("companyName")
                s["dealerLogo"]     = dealer.get("logo")
                s["dealerWhatsapp"] = dealer.get("whatsapp")
                s["dealerPhone"]    = dealer.get("phone")
                s["dealerEmail"]    = dealer.get("email")
                s["dealerId"]       = dealer.get("dealerId")
            result.append(s)
    return result


# ── LIKES ────────────────────────────────────────────────────────────────────

async def toggle_like(user_id: str, car_id: str) -> dict:
    db = get_db()
    # Normalize carId
    if ObjectId.is_valid(car_id):
        car = await db["car_listings"].find_one({"_id": ObjectId(car_id)})
        if car:
            car_id = car.get("carId", car_id)

    existing = await db["car_likes"].find_one({"userId": user_id, "carId": car_id})
    if existing:
        await db["car_likes"].delete_one({"userId": user_id, "carId": car_id})
        await db["car_listings"].update_one({"carId": car_id}, {"$inc": {"likeCount": -1}})
        return {"liked": False}
    else:
        await db["car_likes"].insert_one({
            "userId": user_id, "carId": car_id, "createdAt": datetime.utcnow(),
        })
        await db["car_listings"].update_one({"carId": car_id}, {"$inc": {"likeCount": 1}})
        return {"liked": True}


async def get_user_likes(user_id: str) -> list:
    db = get_db()
    likes = await db["car_likes"].find({"userId": user_id}).to_list(500)
    return [l["carId"] for l in likes]


# ── PROFILE ───────────────────────────────────────────────────────────────────

async def update_user_profile(user_id: str, data: dict) -> dict:
    db = get_db()
    allowed = [
        "fullName", "phone", "whatsapp", "address", "city", "state",
        "country", "bio", "instagram", "facebook", "twitter", "tiktok", "website",
        "showPhone", "showWhatsapp", "showEmail",
    ]
    update = {k: v for k, v in data.items() if k in allowed and v is not None}
    update["updatedAt"] = datetime.utcnow()
    await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": update})
    user = await db["users"].find_one({"_id": ObjectId(user_id)})
    s = serialize_doc(user)
    s.pop("passwordHash", None)
    return s


# ── SPECIAL REQUESTS ──────────────────────────────────────────────────────────

async def create_special_request(user_id: str, data: dict) -> dict:
    db = get_db()
    dealer_id = data.get("dealerId")
    dealer = None

    if dealer_id:
        if ObjectId.is_valid(dealer_id):
            dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
        if not dealer:
            dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})
        if dealer:
            dealer_id = str(dealer["_id"])

    doc = {
        "requestId": gen_id("REQ"),
        "userId": user_id,
        "dealerId": dealer_id,
        "carBrand": data.get("carBrand"),
        "carModel": data.get("carModel"),
        "carYear": data.get("carYear"),
        "carColor": data.get("carColor"),
        "budget": data.get("budget"),
        "paymentType": data.get("paymentType", "full"),
        "description": data.get("description"),
        "status": "pending",
        "dealerResponse": None,
        "dealerResponseAt": None,
        "progress": [],
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    result = await db["special_requests"].insert_one(doc)
    doc["_id"] = result.inserted_id

    if dealer:
        await db["notifications"].insert_one({
            "receiverId": dealer["userId"],
            "senderId": user_id,
            "type": "general",
            "title": "New Special Car Request",
            "message": f"A customer wants {data.get('carBrand','')} {data.get('carModel','')}",
            "isRead": False,
            "data": {"requestId": doc["requestId"]},
            "createdAt": datetime.utcnow(),
        })

    return serialize_doc(doc)


async def get_user_requests(user_id: str) -> list:
    db = get_db()
    requests = await db["special_requests"].find({"userId": user_id}).sort("createdAt", -1).to_list(50)
    result = []
    for r in requests:
        s = serialize_doc(r)
        if r.get("dealerId") and ObjectId.is_valid(r["dealerId"]):
            dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(r["dealerId"])})
            s["dealerName"] = dealer.get("companyName") if dealer else "—"
        result.append(s)
    return result


async def get_dealer_requests(dealer_id: str) -> list:
    db = get_db()
    requests = await db["special_requests"].find({"dealerId": dealer_id}).sort("createdAt", -1).to_list(50)
    result = []
    for r in requests:
        s = serialize_doc(r)
        user = await db["users"].find_one({"_id": ObjectId(r["userId"])})
        s["userName"] = user.get("fullName") if user else "—"
        s["userPhone"] = user.get("phone") if user else "—"
        result.append(s)
    return result


async def respond_to_request(request_id: str, dealer_id: str, response: str, progress_note: str = None) -> dict:
    db = get_db()
    req = await db["special_requests"].find_one({"requestId": request_id, "dealerId": dealer_id})
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    update = {
        "dealerResponse": response,
        "status": "responded",
        "dealerResponseAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }
    await db["special_requests"].update_one({"requestId": request_id}, {"$set": update})
    if progress_note:
        await db["special_requests"].update_one(
            {"requestId": request_id},
            {"$push": {"progress": {"note": progress_note, "at": datetime.utcnow().isoformat()}}}
        )
    await db["notifications"].insert_one({
        "receiverId": req["userId"], "type": "general",
        "title": "Dealer Responded to Your Request",
        "message": response[:100], "isRead": False, "createdAt": datetime.utcnow(),
    })
    return {"message": "Response sent"}


# ── APPOINTMENTS ──────────────────────────────────────────────────────────────

async def create_appointment(user_id: str, data: dict) -> dict:
    db = get_db()
    dealer_id_input = data.get("dealerId", "")
    dealer = None

    if ObjectId.is_valid(dealer_id_input):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id_input)})
    if not dealer:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id_input})

    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found. Use the Dealer ID (e.g. DLR-XXXXXXXX)")

    dealer_mongo_id = str(dealer["_id"])

    doc = {
        "appointmentId": gen_id("APT"),
        "userId": user_id,
        "dealerId": dealer_mongo_id,
        "type": data.get("type", "showroom_visit"),
        "scheduledAt": data.get("scheduledAt"),
        "notes": data.get("notes"),
        "status": "pending",
        "dealerConfirmedAt": None,
        "createdAt": datetime.utcnow(),
    }
    result = await db["appointments"].insert_one(doc)
    doc["_id"] = result.inserted_id

    await db["notifications"].insert_one({
        "receiverId": dealer["userId"],
        "senderId": user_id,
        "type": "general",
        "title": "New Appointment Request",
        "message": f"Someone wants to schedule a {data.get('type','visit').replace('_',' ')}",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    return serialize_doc(doc)


async def get_user_appointments(user_id: str) -> list:
    db = get_db()
    apts = await db["appointments"].find({"userId": user_id}).sort("scheduledAt", -1).to_list(50)
    result = []
    for a in apts:
        s = serialize_doc(a)
        if a.get("dealerId") and ObjectId.is_valid(a["dealerId"]):
            dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(a["dealerId"])})
            if dealer:
                s["dealerName"]     = dealer.get("companyName")
                s["dealerPhone"]    = dealer.get("phone")
                s["dealerWhatsapp"] = dealer.get("whatsapp")
        result.append(s)
    return result


async def get_all_users_admin(search: str = None, role: str = None, skip: int = 0, limit: int = 20) -> dict:
    db = get_db()
    query = {}
    if role:
        query["role"] = role
    if search:
        query["$or"] = [
            {"fullName": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"username": {"$regex": search, "$options": "i"}},
            {"phone": {"$regex": search, "$options": "i"}},
        ]
    total = await db["users"].count_documents(query)
    users = await db["users"].find(query).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    clean = []
    for u in users:
        s = serialize_doc(u)
        s.pop("passwordHash", None)
        clean.append(s)
    return {"total": total, "users": clean, "skip": skip, "limit": limit}
