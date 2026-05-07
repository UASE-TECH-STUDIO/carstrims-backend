from datetime import datetime
from bson import ObjectId
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc


async def get_dealer_stats_full(dealer_id: str) -> dict:
    db = get_db()

    total_cars = await db["car_listings"].count_documents({"dealerId": dealer_id})
    available_cars = await db["car_listings"].count_documents({"dealerId": dealer_id, "status": "available"})
    sold_cars = await db["car_listings"].count_documents({"dealerId": dealer_id, "status": "sold"})
    total_staff = await db["staff_accounts"].count_documents({"dealerId": dealer_id})
    total_partners = await db["partner_links"].count_documents({"dealerId": dealer_id, "status": "approved"})
    pending_partners = await db["partner_links"].count_documents({"dealerId": dealer_id, "status": "pending"})

    # Count ALL requests — both dealer-specific and general (no dealerId)
    pending_requests = await db["special_requests"].count_documents({
        "$or": [
            {"dealerId": dealer_id, "status": "pending"},
            {"dealerId": None, "status": "pending"},
            {"dealerId": {"$exists": False}, "status": "pending"},
        ]
    })

    pending_appointments = await db["appointments"].count_documents({
        "dealerId": dealer_id, "status": "pending"
    })

    # Sales summary
    sales_pipeline = [
        {"$match": {"dealerId": dealer_id}},
        {"$group": {
            "_id": None,
            "totalRevenue": {"$sum": "$sellingPrice"},
            "totalProfit": {"$sum": "$profit"},
            "totalNetProfit": {"$sum": "$netProfit"},
            "totalSales": {"$sum": 1},
        }},
    ]
    sales_result = await db["sale_transactions"].aggregate(sales_pipeline).to_list(1)
    sales_data = sales_result[0] if sales_result else {
        "totalRevenue": 0, "totalProfit": 0, "totalNetProfit": 0, "totalSales": 0
    }

    # Expenses total
    exp_pipeline = [
        {"$match": {"dealerId": dealer_id}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]
    exp_result = await db["expense_records"].aggregate(exp_pipeline).to_list(1)
    total_expenses = exp_result[0]["total"] if exp_result else 0

    return {
        "totalCars": total_cars,
        "availableCars": available_cars,
        "soldCars": sold_cars,
        "totalStaff": total_staff,
        "totalPartners": total_partners,
        "pendingPartners": pending_partners,
        "pendingRequests": pending_requests,
        "pendingAppointments": pending_appointments,
        "totalRevenue": sales_data.get("totalRevenue", 0),
        "totalProfit": sales_data.get("totalProfit", 0),
        "totalNetProfit": sales_data.get("totalNetProfit", 0),
        "totalSales": sales_data.get("totalSales", 0),
        "totalExpenses": total_expenses,
    }


async def get_dealer_notifications(dealer_id: str, user_id: str, skip: int = 0, limit: int = 50) -> dict:
    db = get_db()
    total = await db["notifications"].count_documents({"receiverId": user_id})
    notifs = await db["notifications"].find(
        {"receiverId": user_id}
    ).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    unread = await db["notifications"].count_documents({"receiverId": user_id, "isRead": False})
    return {
        "total": total,
        "unreadCount": unread,
        "notifications": [serialize_doc(n) for n in notifs],
    }


async def mark_notification_read(notif_id: str, user_id: str) -> dict:
    db = get_db()
    await db["notifications"].update_one(
        {"$or": [
            {"_id": ObjectId(notif_id) if ObjectId.is_valid(notif_id) else None},
            {"notifId": notif_id},
        ], "receiverId": user_id},
        {"$set": {"isRead": True, "readAt": datetime.utcnow()}},
    )
    return {"message": "Marked as read"}


async def mark_all_read(user_id: str) -> dict:
    db = get_db()
    await db["notifications"].update_many(
        {"receiverId": user_id, "isRead": False},
        {"$set": {"isRead": True, "readAt": datetime.utcnow()}},
    )
    return {"message": "All marked as read"}


async def get_dealer_reports(dealer_id: str) -> dict:
    db = get_db()

    # Monthly sales last 6 months
    from datetime import timedelta
    now = datetime.utcnow()
    monthly = []
    for i in range(5, -1, -1):
        month_start = (now.replace(day=1) - timedelta(days=30*i)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        month_end = (month_start + timedelta(days=32)).replace(day=1)
        month_sales = await db["sale_transactions"].aggregate([
            {"$match": {"dealerId": dealer_id, "soldAt": {"$gte": month_start, "$lt": month_end}}},
            {"$group": {"_id": None, "revenue": {"$sum": "$sellingPrice"}, "profit": {"$sum": "$profit"}, "count": {"$sum": 1}}},
        ]).to_list(1)
        data = month_sales[0] if month_sales else {"revenue": 0, "profit": 0, "count": 0}
        monthly.append({
            "month": month_start.strftime("%b %Y"),
            "revenue": data.get("revenue", 0),
            "profit": data.get("profit", 0),
            "count": data.get("count", 0),
        })

    # Top brands sold
    brand_pipeline = [
        {"$match": {"dealerId": dealer_id}},
        {"$group": {"_id": "$carBrand", "count": {"$sum": 1}, "revenue": {"$sum": "$sellingPrice"}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    top_brands = await db["sale_transactions"].aggregate(brand_pipeline).to_list(5)

    # Payment method breakdown
    pay_pipeline = [
        {"$match": {"dealerId": dealer_id}},
        {"$group": {"_id": "$paymentMethod", "count": {"$sum": 1}, "total": {"$sum": "$sellingPrice"}}},
    ]
    payment_breakdown = await db["sale_transactions"].aggregate(pay_pipeline).to_list(10)

    # Staff performance
    staff_pipeline = [
        {"$match": {"dealerId": dealer_id}},
        {"$group": {"_id": "$staffId", "sales": {"$sum": 1}, "revenue": {"$sum": "$sellingPrice"}}},
        {"$sort": {"sales": -1}},
        {"$limit": 5},
    ]
    staff_perf_raw = await db["sale_transactions"].aggregate(staff_pipeline).to_list(5)
    staff_perf = []
    for s in staff_perf_raw:
        if s["_id"]:
            staff = await db["users"].find_one({"_id": ObjectId(s["_id"])})
            staff_perf.append({
                "name": staff.get("fullName", "Unknown") if staff else "Unknown",
                "sales": s["sales"],
                "revenue": s["revenue"],
            })

    # Expenses by category
    exp_pipeline = [
        {"$match": {"dealerId": dealer_id}},
        {"$group": {"_id": "$category", "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}},
    ]
    expenses_by_cat = await db["expense_records"].aggregate(exp_pipeline).to_list(10)

    stats = await get_dealer_stats_full(dealer_id)

    return {
        "summary": stats,
        "monthlySales": monthly,
        "topBrands": [{"brand": b["_id"] or "Unknown", "count": b["count"], "revenue": b["revenue"]} for b in top_brands],
        "paymentBreakdown": [{"method": p["_id"] or "cash", "count": p["count"], "total": p["total"]} for p in payment_breakdown],
        "staffPerformance": staff_perf,
        "expensesByCategory": [{"category": e["_id"] or "other", "total": e["total"], "count": e["count"]} for e in expenses_by_cat],
    }
