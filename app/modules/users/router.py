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
    condition: Optional[str] = None
    transmission: Optional[str] = None
    fuelType: Optional[str] = None
    referencePhoto: Optional[str] = None
    referencePhotos: Optional[list] = None


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


#  FAVORITES  unified "favorites" collection 
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


#  REQUESTS 
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
        "condition": data.condition, "transmission": data.transmission,
        "fuelType": data.fuelType,
        "referencePhoto": data.referencePhoto,
        "referencePhotos": data.referencePhotos or (
            [data.referencePhoto] if data.referencePhoto else []
        ),
        "status": "pending", "dealerResponse": None,
        "journey": None,
        "createdAt": datetime.utcnow(), "updatedAt": datetime.utcnow(),
    }
    await db["car_requests"].insert_one(doc)
    return serialize_doc(doc)


#  APPOINTMENTS 
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


#  SPECIAL ORDER REQUEST FLOW 

@router.post("/requests/{request_id}/accept")
async def buyer_accept_request(
    request_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Buyer accepts dealer's counter-offer and starts the journey."""
    db = get_db()
    uid = str(current_user["_id"])
    req = await db["car_requests"].find_one(
        {"$or": [{"requestId": request_id}, {"_id": ObjectId(request_id) if ObjectId.is_valid(request_id) else None}], "userId": uid}
    )
    if not req:
        from fastapi import HTTPException
        raise HTTPException(404, "Request not found")

    await db["car_requests"].update_one(
        {"_id": req["_id"]},
        {"$set": {"status": "accepted", "journeyStarted": True, "journeyStartedAt": datetime.utcnow(), "updatedAt": datetime.utcnow()}}
    )
    # Notify dealer
    if req.get("dealerId") and ObjectId.is_valid(str(req["dealerId"])):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(req["dealerId"])})
        if dealer and dealer.get("userId"):
            await db["notifications"].insert_one({
                "receiverId": str(dealer["userId"]), "senderId": uid,
                "type": "request", "title": "Order Accepted!",
                "message": f"{current_user.get('fullName','Buyer')} accepted your offer. The journey begins!",
                "isRead": False, "createdAt": datetime.utcnow(),
                "data": {"requestId": request_id},
            })
    return {"message": "Accepted. Journey started!"}


@router.post("/requests/{request_id}/decline")
async def buyer_decline_request(
    request_id: str,
    data: dict = Body({}),
    current_user: dict = Depends(get_current_user),
):
    """Buyer declines dealer's counter-offer."""
    db = get_db()
    uid = str(current_user["_id"])
    req = await db["car_requests"].find_one(
        {"$or": [{"requestId": request_id}, {"_id": ObjectId(request_id) if ObjectId.is_valid(request_id) else None}], "userId": uid}
    )
    if not req:
        from fastapi import HTTPException
        raise HTTPException(404, "Request not found")

    await db["car_requests"].update_one(
        {"_id": req["_id"]},
        {"$set": {"status": "declined", "buyerDeclineReason": data.get("reason", ""), "updatedAt": datetime.utcnow()}}
    )
    return {"message": "Offer declined"}


@router.post("/requests/{request_id}/cancel")
async def buyer_cancel_request(
    request_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Buyer cancels their own pending request."""
    db = get_db()
    uid = str(current_user["_id"])
    req = await db["car_requests"].find_one(
        {"$or": [{"requestId": request_id}, {"_id": ObjectId(request_id) if ObjectId.is_valid(request_id) else None}], "userId": uid}
    )
    if not req:
        from fastapi import HTTPException
        raise HTTPException(404, "Request not found")

    await db["car_requests"].update_one(
        {"_id": req["_id"]},
        {"$set": {"status": "cancelled", "updatedAt": datetime.utcnow()}}
    )
    return {"message": "Request cancelled"}


@router.get("/requests/dealer")
async def get_dealer_requests(
    status: str = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Dealer: returns all requests from car_requests collection.
    - General requests (no dealerId): visible to ALL dealers while status=pending
    - Specific requests (dealerId = this dealer): always visible to this dealer
    - Once a dealer accepts, dealerId is set to that dealer -> disappears from others
    """
    db = get_db()
    from app.modules.dealers.service import get_dealer_by_user_id

    try:
        dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(403, "Not a dealer account")

    dealer_id = str(dealer["_id"])

    # Build query:
    # Show requests that are either:
    # (a) specifically directed at this dealer, OR
    # (b) general (no dealerId / null dealerId) and still pending
    query = {
        "$or": [
            {"dealerId": dealer_id},                             # targeted at this dealer
            {"dealerId": None, "status": "pending"},             # general, still open
            {"dealerId": {"$exists": False}, "status": "pending"}, # general (no field)
        ]
    }

    # Optional status filter
    if status and status != "all":
        # For status filter, override the OR - just filter by dealerId + status
        query = {
            "$or": [
                {"dealerId": dealer_id, "status": status},
                {"dealerId": None, "status": status},
                {"dealerId": {"$exists": False}, "status": status},
            ]
        }

    reqs = await db["car_requests"].find(query).sort("createdAt", -1).to_list(200)

    result = []
    for r in reqs:
        s = serialize_doc(r)
        # Enrich with buyer info
        if r.get("userId") and ObjectId.is_valid(str(r["userId"])):
            buyer = await db["users"].find_one({"_id": ObjectId(r["userId"])})
            if buyer:
                s["buyerName"] = buyer.get("fullName") or r.get("userName")
                s["buyerPhone"] = buyer.get("phone") or r.get("userPhone")
                s["buyerWhatsapp"] = buyer.get("whatsapp")
                s["buyerEmail"] = buyer.get("email")
                s["buyerAvatar"] = buyer.get("avatar") or buyer.get("profilePicture")
                s["buyerUserId"] = str(buyer["_id"])
        result.append(s)

    return result


@router.get("/requests/{request_id}")
async def get_request_detail(
    request_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get full detail of a single request (buyer or dealer can access)."""
    db = get_db()
    uid = str(current_user["_id"])
    role = current_user.get("role", "")

    q = {"$or": [{"requestId": request_id}]}
    if ObjectId.is_valid(request_id):
        q["$or"].append({"_id": ObjectId(request_id)})

    req = await db["car_requests"].find_one(q)
    if not req:
        from fastapi import HTTPException
        raise HTTPException(404, "Request not found")

    s = serialize_doc(req)
    # Enrich buyer info
    if req.get("userId") and ObjectId.is_valid(req["userId"]):
        buyer = await db["users"].find_one({"_id": ObjectId(req["userId"])})
        if buyer:
            s["buyerName"] = buyer.get("fullName")
            s["buyerPhone"] = buyer.get("phone")
            s["buyerWhatsapp"] = buyer.get("whatsapp")
            s["buyerEmail"] = buyer.get("email")
    return s


#  DEALER: RESPOND TO REQUESTS 

@router.post("/requests/{request_id}/respond")
async def dealer_respond_to_request(
    request_id: str,
    data: dict = Body({}),
    current_user: dict = Depends(get_current_user),
):
    """
    Dealer responds to a request. Can:
    - accept: confirm they can fulfil the original request
    - counter: offer an alternative car with full details
    Accepted request disappears from general pool, stays on this dealer only.
    """
    db = get_db()
    from app.modules.dealers.service import get_dealer_by_user_id
    try:
        dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(403, "Not a dealer")

    req = None
    if ObjectId.is_valid(request_id):
        req = await db["car_requests"].find_one({"_id": ObjectId(request_id)})
    if not req:
        req = await db["car_requests"].find_one({"requestId": request_id})
    if not req:
        from fastapi import HTTPException
        raise HTTPException(404, "Request not found")

    response_type = data.get("type", "accept")  # "accept" | "counter"
    update = {
        "dealerId": str(dealer["_id"]),
        "dealerName": dealer.get("companyName"),
        "dealerResponse": data.get("message", ""),
        "dealerResponseAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    if response_type == "counter":
        update["status"] = "countered"
        update["counterOffer"] = {
            "carBrand": data.get("altBrand", ""),
            "carModel": data.get("altModel", ""),
            "carYear": data.get("altYear"),
            "carColor": data.get("altColor", ""),
            "condition": data.get("altCondition", ""),
            "price": data.get("altPrice"),
            "currency": data.get("altCurrency", "NGN"),
            "description": data.get("altDescription", ""),
            "estimatedDelivery": data.get("estimatedDelivery", ""),
            "images": data.get("altImages", []),
            "offeredAt": datetime.utcnow(),
        }
    else:
        update["status"] = "accepted_by_dealer"
        update["journeyStarted"] = True
        update["journeyStartedAt"] = datetime.utcnow()
        # Setup empty journey milestones
        update["journey"] = {
            "paymentPlan": data.get("paymentPlan"),  # {"type": "installmental", "installments": [...]}
            "milestones": [],
        }

    await db["car_requests"].update_one({"_id": req["_id"]}, {"$set": update})

    # Notify buyer
    if req.get("userId") and ObjectId.is_valid(req["userId"]):
        title = "Dealer Responded to Your Request"
        msg = (f"{dealer.get('companyName')} can fulfil your request! The journey begins."
               if response_type == "accept"
               else f"{dealer.get('companyName')} has an alternative offer for your vehicle request.")
        await db["notifications"].insert_one({
            "receiverId": req["userId"], "senderId": str(current_user["_id"]),
            "type": "request", "title": title, "message": msg,
            "isRead": False, "createdAt": datetime.utcnow(),
            "data": {"requestId": request_id},
        })

    return {"message": "Response sent", "status": update["status"]}


@router.post("/requests/{request_id}/milestone")
async def add_journey_milestone(
    request_id: str,
    data: dict = Body({}),
    current_user: dict = Depends(get_current_user),
):
    """
    Dealer adds a shipping/journey milestone with optional evidence.
    Stages: payment_received | car_purchased | shipped | arrived_country | in_transit | delivered
    """
    db = get_db()
    from app.modules.dealers.service import get_dealer_by_user_id
    try:
        dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(403, "Not a dealer")

    req = None
    if ObjectId.is_valid(request_id):
        req = await db["car_requests"].find_one({"_id": ObjectId(request_id)})
    if not req:
        req = await db["car_requests"].find_one({"requestId": request_id})
    if not req:
        from fastapi import HTTPException
        raise HTTPException(404, "Request not found")

    milestone = {
        "id": gen_id("MS"),
        "stage": data.get("stage", "update"),
        "title": data.get("title", "Update"),
        "description": data.get("description", ""),
        "evidence": data.get("evidence", []),  # list of image/doc URLs
        "addedAt": datetime.utcnow(),
        "addedBy": "dealer",
    }

    await db["car_requests"].update_one(
        {"_id": req["_id"]},
        {
            "$push": {"journey.milestones": milestone},
            "$set": {"updatedAt": datetime.utcnow(), "lastMilestoneStage": data.get("stage")},
        }
    )

    # If final delivery stage, mark completed
    if data.get("stage") == "delivered":
        await db["car_requests"].update_one(
            {"_id": req["_id"]},
            {"$set": {"status": "completed", "completedAt": datetime.utcnow()}}
        )

    # Notify buyer
    if req.get("userId") and ObjectId.is_valid(req["userId"]):
        await db["notifications"].insert_one({
            "receiverId": req["userId"], "senderId": str(current_user["_id"]),
            "type": "request_update",
            "title": f"Order Update: {data.get('title', 'New update')}",
            "message": data.get("description", "Your order has been updated."),
            "isRead": False, "createdAt": datetime.utcnow(),
            "data": {"requestId": request_id, "stage": data.get("stage")},
        })

    return {"message": "Milestone added", "milestone": milestone}


@router.post("/requests/{request_id}/payment-plan")
async def set_payment_plan(
    request_id: str,
    data: dict = Body({}),
    current_user: dict = Depends(get_current_user),
):
    """Dealer sets up the payment plan for an accepted request."""
    db = get_db()
    from app.modules.dealers.service import get_dealer_by_user_id
    try:
        dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(403, "Not a dealer")

    req = None
    if ObjectId.is_valid(request_id):
        req = await db["car_requests"].find_one({"_id": ObjectId(request_id)})
    if not req:
        req = await db["car_requests"].find_one({"requestId": request_id})
    if not req:
        from fastapi import HTTPException
        raise HTTPException(404, "Request not found")

    plan = {
        "type": data.get("type", "full"),  # "full" | "installmental"
        "totalAmount": data.get("totalAmount"),
        "currency": data.get("currency", "NGN"),
        "installments": data.get("installments", []),  # [{amount, dueDate, label, paid: false}]
        "createdAt": datetime.utcnow(),
    }

    await db["car_requests"].update_one(
        {"_id": req["_id"]},
        {"$set": {"journey.paymentPlan": plan, "updatedAt": datetime.utcnow()}}
    )

    # Notify buyer
    if req.get("userId") and ObjectId.is_valid(req["userId"]):
        await db["notifications"].insert_one({
            "receiverId": req["userId"], "senderId": str(current_user["_id"]),
            "type": "request",
            "title": "Payment Plan Set",
            "message": f"Your dealer has set up a payment plan for your order.",
            "isRead": False, "createdAt": datetime.utcnow(),
            "data": {"requestId": request_id},
        })

    return {"message": "Payment plan saved", "plan": plan}


@router.patch("/requests/{request_id}/payment/{installment_index}")
async def mark_installment_paid(
    request_id: str,
    installment_index: int,
    data: dict = Body({}),
    current_user: dict = Depends(get_current_user),
):
    """Dealer marks an installment as paid with optional receipt evidence."""
    db = get_db()
    req = None
    if ObjectId.is_valid(request_id):
        req = await db["car_requests"].find_one({"_id": ObjectId(request_id)})
    if not req:
        req = await db["car_requests"].find_one({"requestId": request_id})
    if not req:
        from fastapi import HTTPException
        raise HTTPException(404, "Request not found")

    field = f"journey.paymentPlan.installments.{installment_index}"
    await db["car_requests"].update_one(
        {"_id": req["_id"]},
        {"$set": {
            f"{field}.paid": True,
            f"{field}.paidAt": datetime.utcnow(),
            f"{field}.evidence": data.get("evidence", ""),
            "updatedAt": datetime.utcnow(),
        }}
    )
    return {"message": "Payment recorded"}