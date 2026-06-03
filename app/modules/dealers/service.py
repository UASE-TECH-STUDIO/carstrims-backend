from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException, status
from app.database.connection import get_db
from app.modules.dealers.models import DealerStatus
import random
import string


def generate_dealer_id():
    chars = string.ascii_uppercase + string.digits
    return "DLR-" + "".join(random.choices(chars, k=8))


def serialize_doc(doc: dict) -> dict:
    if doc is None:
        return None
    result = {}
    for key, value in doc.items():
        if isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, dict):
            result[key] = serialize_doc(value)
        elif isinstance(value, list):
            result[key] = [
                serialize_doc(i) if isinstance(i, dict)
                else (str(i) if isinstance(i, ObjectId) else i)
                for i in value
            ]
        else:
            result[key] = value
    return result


def build_dealer_query(dealer_id: str) -> dict:
    """Accept either MongoDB _id or dealerId like DLR-XXXXXXXX"""
    if ObjectId.is_valid(dealer_id):
        return {"_id": ObjectId(dealer_id)}
    return {"dealerId": dealer_id}


async def create_dealer_profile(user_id: str, data: dict) -> dict:
    db = get_db()

    existing = await db["dealer_organizations"].find_one({"userId": user_id})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dealer profile already exists for this account",
        )

    user = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    dealer_doc = {
        "dealerId": generate_dealer_id(),
        "userId": user_id,
        "companyName": data.get("companyName"),
        "ownerName": user["fullName"],
        "email": data.get("email", user["email"]),
        "phone": data.get("phone", user["phone"]),
        "whatsapp": data.get("whatsapp"),
        "address": data.get("address"),
        "city": data.get("city"),
        "state": data.get("state"),
        "country": data.get("country", "Nigeria"),
        "logo": data.get("logo"),
        "banner": data.get("banner"),
        "passportPhoto": data.get("passportPhoto"),
        "description": data.get("description"),
        "status": DealerStatus.AWAITING_APPROVAL.value,
        "qrCode": None,
        "subscriptionPlan": "free",
        "totalCarsListed": 0,
        "totalCarsSold": 0,
        "totalRevenue": 0.0,
        "warningNote": None,
        "approvedAt": None,
        "approvedBy": None,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    result = await db["dealer_organizations"].insert_one(dealer_doc)
    dealer_doc["_id"] = result.inserted_id

    await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {
            "dealerId": str(result.inserted_id),
            "updatedAt": datetime.utcnow(),
        }},
    )

    return serialize_doc(dealer_doc)


async def get_all_dealers(
    status_filter: str = None,
    search: str = None,
    skip: int = 0,
    limit: int = 20,
) -> dict:
    db = get_db()
    query = {}

    if status_filter:
        query["status"] = status_filter

    if search:
        query["$or"] = [
            {"companyName": {"$regex": search, "$options": "i"}},
            {"ownerName": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"dealerId": {"$regex": search, "$options": "i"}},
        ]

    total = await db["dealer_organizations"].count_documents(query)
    dealers = await db["dealer_organizations"].find(query).skip(skip).limit(limit).to_list(limit)

    return {
        "total": total,
        "dealers": [serialize_doc(d) for d in dealers],
        "skip": skip,
        "limit": limit,
    }


async def get_dealer_by_id(dealer_id: str) -> dict:
    db = get_db()
    query = build_dealer_query(dealer_id)
    dealer = await db["dealer_organizations"].find_one(query)
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found")
    return serialize_doc(dealer)


async def get_dealer_by_user_id(user_id: str, current_user: dict = None) -> dict:
    """
    Resolves the dealer for a user_id.
    If current_user has _resolved_dealer_id (staff), uses that directly.
    """
    db = get_db()

    # Staff: dealer id already resolved by dependency
    if current_user and current_user.get("_resolved_dealer_id"):
        from bson import ObjectId
        dealer_id = current_user["_resolved_dealer_id"]
        if ObjectId.is_valid(dealer_id):
            dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
        else:
            dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})
        if dealer:
            return serialize_doc(dealer)

    dealer = await db["dealer_organizations"].find_one({"userId": user_id})
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer profile not found")
    return serialize_doc(dealer)


async def approve_dealer(dealer_id: str, admin_id: str) -> dict:
    db = get_db()
    query = build_dealer_query(dealer_id)
    dealer = await db["dealer_organizations"].find_one(query)
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found")

    await db["dealer_organizations"].update_one(
        {"_id": dealer["_id"]},
        {"$set": {
            "status": "approved",
            "approvedAt": datetime.utcnow(),
            "approvedBy": admin_id,
            "updatedAt": datetime.utcnow(),
        }},
    )

    await db["users"].update_one(
        {"_id": ObjectId(dealer["userId"])},
        {"$set": {"status": "active", "updatedAt": datetime.utcnow()}},
    )

    await db["notifications"].insert_one({
        "receiverId": dealer["userId"],
        "senderId": admin_id,
        "type": "dealer_approved",
        "title": "Account Approved",
        "message": "Congratulations! Your dealer account has been approved. You now have full access.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    # Fire push notification
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(
            dealer["userId"],
            "Account Approved",
            "Congratulations! Your dealer account has been approved. You now have full access.",
            "/dashboard",
        ))
    except Exception as _pe:
        pass

    return {"message": "Dealer approved successfully", "dealerId": dealer["dealerId"]}


async def reject_dealer(dealer_id: str, admin_id: str, reason: str = None) -> dict:
    db = get_db()
    query = build_dealer_query(dealer_id)
    dealer = await db["dealer_organizations"].find_one(query)
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found")

    await db["dealer_organizations"].update_one(
        {"_id": dealer["_id"]},
        {"$set": {
            "status": DealerStatus.REJECTED.value,
            "warningNote": reason,
            "updatedAt": datetime.utcnow(),
        }},
    )

    await db["notifications"].insert_one({
        "receiverId": dealer["userId"],
        "senderId": admin_id,
        "type": "general",
        "title": "Account Registration Rejected",
        "message": reason or "Your dealer registration was not approved. Please contact support.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    # Fire push notification
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(
            dealer["userId"],
            "Account Registration Rejected",
            reason or "Your dealer registration was not approved. Please contact support.",
            "/dashboard",
        ))
    except Exception as _pe:
        pass

    return {"message": "Dealer rejected"}


async def suspend_dealer(dealer_id: str, admin_id: str, reason: str = None) -> dict:
    db = get_db()
    query = build_dealer_query(dealer_id)
    dealer = await db["dealer_organizations"].find_one(query)
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found")

    await db["dealer_organizations"].update_one(
        {"_id": dealer["_id"]},
        {"$set": {
            "status": DealerStatus.SUSPENDED.value,
            "warningNote": reason,
            "updatedAt": datetime.utcnow(),
        }},
    )

    await db["users"].update_one(
        {"_id": ObjectId(dealer["userId"])},
        {"$set": {"status": "suspended", "updatedAt": datetime.utcnow()}},
    )

    await db["notifications"].insert_one({
        "receiverId": dealer["userId"],
        "senderId": admin_id,
        "type": "dealer_suspended",
        "title": "Account Suspended",
        "message": reason or "Your account has been suspended. Please contact support.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    # Fire push notification
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(
            dealer["userId"],
            "Account Suspended",
            reason or "Your account has been suspended. Please contact support.",
            "/dashboard",
        ))
    except Exception as _pe:
        pass

    return {"message": "Dealer suspended"}


async def update_dealer_profile(dealer_id: str, data: dict) -> dict:
    db = get_db()
    query = build_dealer_query(dealer_id)
    dealer = await db["dealer_organizations"].find_one(query)
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found")

    data["updatedAt"] = datetime.utcnow()
    data.pop("_id", None)
    data.pop("userId", None)
    data.pop("status", None)

    await db["dealer_organizations"].update_one({"_id": dealer["_id"]}, {"$set": data})
    return await get_dealer_by_id(str(dealer["_id"]))


async def get_dealer_stats(dealer_id: str) -> dict:
    db = get_db()

    total_cars = await db["car_listings"].count_documents({"dealerId": dealer_id})
    available_cars = await db["car_listings"].count_documents({"dealerId": dealer_id, "status": "available"})
    sold_cars = await db["car_listings"].count_documents({"dealerId": dealer_id, "status": "sold"})
    total_staff = await db["staff_accounts"].count_documents({"dealerId": dealer_id})
    total_partners = await db["partner_links"].count_documents({"dealerId": dealer_id, "status": "approved"})
    pending_requests = await db["special_requests"].count_documents({"dealerId": dealer_id, "status": "pending"})

    sales_pipeline = [
        {"$match": {"dealerId": dealer_id}},
        {"$group": {"_id": None, "totalRevenue": {"$sum": "$sellingPrice"}, "totalProfit": {"$sum": "$profit"}}},
    ]
    sales_result = await db["sale_transactions"].aggregate(sales_pipeline).to_list(1)
    sales_data = sales_result[0] if sales_result else {"totalRevenue": 0, "totalProfit": 0}

    return {
        "totalCars": total_cars,
        "availableCars": available_cars,
        "soldCars": sold_cars,
        "totalStaff": total_staff,
        "totalPartners": total_partners,
        "pendingRequests": pending_requests,
        "totalRevenue": sales_data.get("totalRevenue", 0),
        "totalProfit": sales_data.get("totalProfit", 0),
    }