from datetime import datetime, timedelta
from bson import ObjectId
from fastapi import HTTPException
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc
from app.auth.password import hash_password
import random
import string


async def get_platform_stats() -> dict:
    db = get_db()

    total_dealers = await db["dealer_organizations"].count_documents({})
    active_dealers = await db["dealer_organizations"].count_documents({"status": "approved"})
    pending_dealers = await db["dealer_organizations"].count_documents({"status": "awaiting_approval"})
    suspended_dealers = await db["dealer_organizations"].count_documents({"status": "suspended"})
    total_users = await db["users"].count_documents({})
    total_cars = await db["car_listings"].count_documents({})
    total_sold = await db["car_listings"].count_documents({"status": "sold"})
    total_staff = await db["staff_accounts"].count_documents({})
    total_partners = await db["partner_links"].count_documents({"status": "approved"})

    rev_pipeline = [
        {"$group": {"_id": None, "total": {"$sum": "$sellingPrice"}, "count": {"$sum": 1}}}
    ]
    rev_result = await db["sale_transactions"].aggregate(rev_pipeline).to_list(1)
    total_revenue = rev_result[0]["total"] if rev_result else 0
    total_transactions = rev_result[0]["count"] if rev_result else 0

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0)
    month_dealers = await db["dealer_organizations"].count_documents(
        {"createdAt": {"$gte": month_start}}
    )
    month_sales = await db["sale_transactions"].aggregate([
        {"$match": {"soldAt": {"$gte": month_start}}},
        {"$group": {"_id": None, "total": {"$sum": "$sellingPrice"}, "count": {"$sum": 1}}},
    ]).to_list(1)
    month_revenue = month_sales[0]["total"] if month_sales else 0
    month_transactions = month_sales[0]["count"] if month_sales else 0

    return {
        "dealers": {
            "total": total_dealers,
            "active": active_dealers,
            "pending": pending_dealers,
            "suspended": suspended_dealers,
            "thisMonth": month_dealers,
        },
        "users": {"total": total_users, "staff": total_staff, "partners": total_partners},
        "inventory": {"totalCars": total_cars, "totalSold": total_sold},
        "revenue": {
            "allTime": total_revenue,
            "thisMonth": month_revenue,
            "totalTransactions": total_transactions,
            "monthTransactions": month_transactions,
        },
    }


async def get_all_dealers_admin(
    status_filter: str = None,
    search: str = None,
    skip: int = 0,
    limit: int = 20,
) -> dict:
    db = get_db()
    query = {}
    if status_filter and status_filter != "all":
        query["status"] = status_filter
    if search:
        query["$or"] = [
            {"companyName": {"$regex": search, "$options": "i"}},
            {"ownerName": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"dealerId": {"$regex": search, "$options": "i"}},
        ]

    total = await db["dealer_organizations"].count_documents(query)
    dealers = await db["dealer_organizations"].find(query).sort(
        "createdAt", -1
    ).skip(skip).limit(limit).to_list(limit)

    enriched = []
    for d in dealers:
        serialized = serialize_doc(d)
        staff_count = await db["staff_accounts"].count_documents({"dealerId": str(d["_id"])})
        car_count = await db["car_listings"].count_documents({"dealerId": str(d["_id"])})
        sold_count = await db["car_listings"].count_documents({"dealerId": str(d["_id"]), "status": "sold"})
        serialized["staffCount"] = staff_count
        serialized["carCount"] = car_count
        serialized["soldCount"] = sold_count
        enriched.append(serialized)

    return {"total": total, "dealers": enriched, "skip": skip, "limit": limit}


async def get_dealer_full_profile(dealer_id: str) -> dict:
    db = get_db()

    if ObjectId.is_valid(dealer_id):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    else:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})

    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found")

    serialized = serialize_doc(dealer)
    did = str(dealer["_id"])

    staff = await db["staff_accounts"].find({"dealerId": did}).to_list(100)
    cars = await db["car_listings"].find({"dealerId": did}).sort("createdAt", -1).limit(10).to_list(10)
    sales = await db["sale_transactions"].find({"dealerId": did}).sort("soldAt", -1).limit(5).to_list(5)

    rev = await db["sale_transactions"].aggregate([
        {"$match": {"dealerId": did}},
        {"$group": {"_id": None, "total": {"$sum": "$sellingPrice"}, "profit": {"$sum": "$profit"}}},
    ]).to_list(1)

    serialized["staff"] = [serialize_doc(s) for s in staff]
    serialized["recentCars"] = [serialize_doc(c) for c in cars]
    serialized["recentSales"] = [serialize_doc(s) for s in sales]
    serialized["totalRevenue"] = rev[0]["total"] if rev else 0
    serialized["totalProfit"] = rev[0]["profit"] if rev else 0

    return serialized


async def get_recent_activity(limit: int = 20) -> list:
    db = get_db()
    activities = []

    recent_sales = await db["sale_transactions"].find({}).sort("soldAt", -1).limit(5).to_list(5)
    for s in recent_sales:
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(s.get("dealerId", ""))}) if ObjectId.is_valid(s.get("dealerId", "")) else None
        activities.append({
            "type": "sale",
            "icon": "",
            "message": f"{dealer.get('companyName', 'A dealer') if dealer else 'A dealer'} sold car {s.get('carId', '')}",
            "amount": s.get("sellingPrice", 0),
            "time": s.get("soldAt", datetime.utcnow()).isoformat() if hasattr(s.get("soldAt", datetime.utcnow()), "isoformat") else str(s.get("soldAt", "")),
        })

    recent_dealers = await db["dealer_organizations"].find({}).sort("createdAt", -1).limit(5).to_list(5)
    for d in recent_dealers:
        activities.append({
            "type": "registration",
            "icon": "",
            "message": f"{d.get('companyName', 'New dealer')} registered",
            "time": d.get("createdAt", datetime.utcnow()).isoformat() if hasattr(d.get("createdAt", datetime.utcnow()), "isoformat") else str(d.get("createdAt", "")),
        })

    recent_cars = await db["car_listings"].find({}).sort("createdAt", -1).limit(5).to_list(5)
    for c in recent_cars:
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(c.get("dealerId", ""))}) if ObjectId.is_valid(c.get("dealerId", "")) else None
        activities.append({
            "type": "car",
            "icon": "",
            "message": f"{dealer.get('companyName', 'A dealer') if dealer else 'A dealer'} listed {c.get('brand', '')} {c.get('model', '')}",
            "time": c.get("createdAt", datetime.utcnow()).isoformat() if hasattr(c.get("createdAt", datetime.utcnow()), "isoformat") else str(c.get("createdAt", "")),
        })

    activities.sort(key=lambda x: x.get("time", ""), reverse=True)
    return activities[:limit]


async def get_growth_chart() -> list:
    db = get_db()
    now = datetime.utcnow()
    months = []

    for i in range(6, 0, -1):
        start = (now.replace(day=1) - timedelta(days=i * 28)).replace(day=1, hour=0, minute=0, second=0)
        end = (start + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0)
        label = start.strftime("%b")

        new_dealers = await db["dealer_organizations"].count_documents(
            {"createdAt": {"$gte": start, "$lt": end}}
        )
        sales_result = await db["sale_transactions"].aggregate([
            {"$match": {"soldAt": {"$gte": start, "$lt": end}}},
            {"$group": {"_id": None, "revenue": {"$sum": "$sellingPrice"}, "count": {"$sum": 1}}},
        ]).to_list(1)

        months.append({
            "month": label,
            "newDealers": new_dealers,
            "revenue": sales_result[0]["revenue"] if sales_result else 0,
            "sales": sales_result[0]["count"] if sales_result else 0,
        })

    return months


async def get_top_dealers(limit: int = 10) -> list:
    db = get_db()
    dealers = await db["dealer_organizations"].find(
        {"status": "approved"}
    ).sort("totalCarsSold", -1).limit(limit).to_list(limit)

    result = []
    for i, d in enumerate(dealers):
        serialized = serialize_doc(d)
        serialized["rank"] = i + 1
        result.append(serialized)

    return result


async def admin_create_dealer(data: dict) -> dict:
    db = get_db()

    existing = await db["users"].find_one({"email": data.get("email")})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    password = data.get("password", "Dealer@" + "".join(random.choices(string.digits, k=6)))

    user_doc = {
        "fullName": data.get("fullName"),
        "username": data.get("username"),
        "email": data.get("email"),
        "phone": data.get("phone", ""),
        "role": "DEALER_ADMIN",
        "passwordHash": hash_password(password),
        "status": "active",
        "dealerId": None,
        "isEmailVerified": True,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
        "lastLogin": None,
    }

    user_result = await db["users"].insert_one(user_doc)
    user_id = str(user_result.inserted_id)

    dealer_doc = {
        "dealerId": "DLR-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8)),
        "userId": user_id,
        "companyName": data.get("companyName"),
        "ownerName": data.get("fullName"),
        "email": data.get("email"),
        "phone": data.get("phone", ""),
        "address": data.get("address", ""),
        "city": data.get("city", ""),
        "state": data.get("state", ""),
        "country": data.get("country", "Nigeria"),
        "status": "approved",
        "approvedAt": datetime.utcnow(),
        "approvedBy": "system",
        "subscriptionPlan": "free",
        "totalCarsListed": 0,
        "totalCarsSold": 0,
        "totalRevenue": 0.0,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    dealer_result = await db["dealer_organizations"].insert_one(dealer_doc)
    await db["users"].update_one(
        {"_id": user_result.inserted_id},
        {"$set": {"dealerId": str(dealer_result.inserted_id)}}
    )

    return {
        "message": "Dealer account created successfully",
        "userId": user_id,
        "dealerId": dealer_doc["dealerId"],
        "email": data.get("email"),
        "tempPassword": password,
    }


async def admin_warn_dealer(dealer_id: str, note: str) -> dict:
    db = get_db()
    if ObjectId.is_valid(dealer_id):
        query = {"_id": ObjectId(dealer_id)}
    else:
        query = {"dealerId": dealer_id}

    await db["dealer_organizations"].update_one(
        query,
        {"$set": {"warningNote": note, "updatedAt": datetime.utcnow()}}
    )

    dealer = await db["dealer_organizations"].find_one(query)
    if dealer:
        await db["notifications"].insert_one({
            "receiverId": dealer["userId"],
            "type": "general",
            "title": "Account Warning",
            "message": note,
            "isRead": False,
            "createdAt": datetime.utcnow(),
        })
# Fire push notification
try:
    import asyncio as _asyncio
    from app.modules.notifications.push_service import send_web_push_to_user as _swpu
    _asyncio.create_task(_swpu(dealer["userId"], "Account Warning", note, "/dashboard"))
except Exception as _pe:
    pass

    return {"message": "Warning sent to dealer"}


async def admin_delete_dealer(dealer_id: str) -> dict:
    db = get_db()
    if ObjectId.is_valid(dealer_id):
        query = {"_id": ObjectId(dealer_id)}
    else:
        query = {"dealerId": dealer_id}

    dealer = await db["dealer_organizations"].find_one(query)
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found")

    await db["dealer_organizations"].update_one(
        query, {"$set": {"status": "deleted", "updatedAt": datetime.utcnow()}}
    )
    await db["users"].update_one(
        {"_id": ObjectId(dealer["userId"])},
        {"$set": {"status": "deleted", "updatedAt": datetime.utcnow()}}
    )

    return {"message": "Dealer account deleted"}


async def admin_reset_password(dealer_user_id: str) -> dict:
    db = get_db()
    new_password = "Reset@" + "".join(random.choices(string.digits + string.ascii_letters, k=8))

    await db["users"].update_one(
        {"_id": ObjectId(dealer_user_id)},
        {"$set": {"passwordHash": hash_password(new_password), "updatedAt": datetime.utcnow()}}
    )

    return {"message": "Password reset successfully", "newPassword": new_password}
