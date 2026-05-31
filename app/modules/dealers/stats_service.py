from datetime import datetime, timedelta
from bson import ObjectId
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc


def _str(v):
    """Ensure dealer_id is always a plain string for queries."""
    return str(v)


async def get_dealer_stats_full(dealer_id) -> dict:
    db  = get_db()
    did = _str(dealer_id)

    total_cars         = await db["car_listings"].count_documents({"dealerId": did})
    available_cars     = await db["car_listings"].count_documents({"dealerId": did, "status": "available"})
    sold_cars          = await db["car_listings"].count_documents({"dealerId": did, "status": "sold"})
    total_staff        = await db["staff_accounts"].count_documents({"dealerId": did})
    total_partners     = await db["partner_links"].count_documents({"dealerId": did, "status": "approved"})
    pending_partners   = await db["partner_links"].count_documents({"dealerId": did, "status": "pending"})

    pending_requests   = await db["car_requests"].count_documents({
        "$or": [
            {"dealerId": did,  "status": "pending"},
            {"dealerId": None, "status": "pending"},
            {"dealerId": {"$exists": False}, "status": "pending"},
        ]
    })

    pending_appointments = await db["appointments"].count_documents(
        {"dealerId": did, "status": "pending"}
    )

    sales_result = await db["sale_transactions"].aggregate([
        {"$match": {"dealerId": did}},
        {"$group": {
            "_id": None,
            "totalRevenue":   {"$sum": "$sellingPrice"},
            "totalProfit":    {"$sum": "$profit"},
            "totalNetProfit": {"$sum": "$netProfit"},
            "totalSales":     {"$sum": 1},
        }},
    ]).to_list(1)
    sd = sales_result[0] if sales_result else {}

    exp_result = await db["expense_records"].aggregate([
        {"$match": {"dealerId": did}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_expenses = exp_result[0]["total"] if exp_result else 0

    return {
        "totalCars":          total_cars,
        "availableCars":      available_cars,
        "soldCars":           sold_cars,
        "totalStaff":         total_staff,
        "totalPartners":      total_partners,
        "pendingPartners":    pending_partners,
        "pendingRequests":    pending_requests,
        "pendingAppointments":pending_appointments,
        "totalRevenue":       sd.get("totalRevenue", 0),
        "totalProfit":        sd.get("totalProfit", 0),
        "totalNetProfit":     sd.get("totalNetProfit", 0),
        "totalSales":         sd.get("totalSales", 0),
        "totalExpenses":      total_expenses,
    }


async def get_dealer_notifications(dealer_id, user_id: str, skip: int = 0, limit: int = 50) -> dict:
    db = get_db()
    total  = await db["notifications"].count_documents({"receiverId": user_id})
    notifs = await db["notifications"].find(
        {"receiverId": user_id}
    ).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    unread = await db["notifications"].count_documents({"receiverId": user_id, "isRead": False})
    return {
        "total":       total,
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


async def get_dealer_reports(dealer_id, date_from=None, date_to=None) -> dict:
    db  = get_db()
    did = _str(dealer_id)
    now = datetime.utcnow()

    #  Build date match dicts 
    sale_match: dict = {"dealerId": did}
    exp_match:  dict = {"dealerId": did}
    if date_from:
        sale_match["soldAt"] = {"$gte": date_from}
        exp_match["date"]    = {"$gte": date_from}
    if date_to:
        sale_match.setdefault("soldAt", {})["$lte"] = date_to
        exp_match.setdefault("date",    {})["$lte"] = date_to

    #  Monthly breakdown 
    monthly = []
    if date_from:
        # Range given: iterate months inside range
        cursor = date_from.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while cursor <= (date_to or now):
            next_m = (cursor + timedelta(days=32)).replace(day=1)
            cap    = min(next_m - timedelta(seconds=1), date_to or now)
            ms = await db["sale_transactions"].aggregate([
                {"$match": {"dealerId": did, "soldAt": {"$gte": cursor, "$lte": cap}}},
                {"$group": {"_id": None,
                    "revenue": {"$sum": "$sellingPrice"},
                    "profit":  {"$sum": "$profit"},
                    "count":   {"$sum": 1}}},
            ]).to_list(1)
            ex = await db["expense_records"].aggregate([
                {"$match": {"dealerId": did, "date": {"$gte": cursor, "$lte": cap}}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
            ]).to_list(1)
            r = ms[0] if ms else {}
            monthly.append({
                "month":    cursor.strftime("%b %Y"),
                "revenue":  r.get("revenue", 0),
                "profit":   r.get("profit",  0),
                "expenses": ex[0]["total"] if ex else 0,
                "count":    r.get("count",   0),
            })
            cursor = next_m
    else:
        # Default: last 6 months
        for i in range(5, -1, -1):
            m_start = (now.replace(day=1) - timedelta(days=30 * i)).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0)
            m_end   = (m_start + timedelta(days=32)).replace(day=1)
            ms = await db["sale_transactions"].aggregate([
                {"$match": {"dealerId": did, "soldAt": {"$gte": m_start, "$lt": m_end}}},
                {"$group": {"_id": None,
                    "revenue": {"$sum": "$sellingPrice"},
                    "profit":  {"$sum": "$profit"},
                    "count":   {"$sum": 1}}},
            ]).to_list(1)
            ex = await db["expense_records"].aggregate([
                {"$match": {"dealerId": did, "date": {"$gte": m_start, "$lt": m_end}}},
                {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
            ]).to_list(1)
            r = ms[0] if ms else {}
            monthly.append({
                "month":    m_start.strftime("%b %Y"),
                "revenue":  r.get("revenue", 0),
                "profit":   r.get("profit",  0),
                "expenses": ex[0]["total"] if ex else 0,
                "count":    r.get("count",   0),
            })

    #  Top brands 
    top_brands = await db["sale_transactions"].aggregate([
        {"$match": sale_match},
        {"$group": {"_id": "$carBrand",
                    "count":   {"$sum": 1},
                    "revenue": {"$sum": "$sellingPrice"}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]).to_list(5)

    #  Payment breakdown 
    payment_breakdown = await db["sale_transactions"].aggregate([
        {"$match": sale_match},
        {"$group": {"_id": "$paymentMethod",
                    "count": {"$sum": 1},
                    "total": {"$sum": "$sellingPrice"}}},
    ]).to_list(10)

    #  Staff performance 
    staff_perf_raw = await db["sale_transactions"].aggregate([
        {"$match": sale_match},
        {"$group": {"_id": "$staffId",
                    "sales":   {"$sum": 1},
                    "revenue": {"$sum": "$sellingPrice"}}},
        {"$sort": {"sales": -1}},
        {"$limit": 5},
    ]).to_list(5)
    staff_perf = []
    for s in staff_perf_raw:
        if s["_id"] and ObjectId.is_valid(str(s["_id"])):
            u = await db["users"].find_one({"_id": ObjectId(s["_id"])})
            staff_perf.append({
                "name":    u.get("fullName", "Unknown") if u else "Unknown",
                "sales":   s["sales"],
                "revenue": s["revenue"],
            })

    #  Expenses by category 
    expenses_by_cat = await db["expense_records"].aggregate([
        {"$match": exp_match},
        {"$group": {"_id": "$category",
                    "total": {"$sum": "$amount"},
                    "count": {"$sum": 1}}},
        {"$sort": {"total": -1}},
    ]).to_list(10)

    #  Summary (filtered or full) 
    if date_from or date_to:
        s_agg = await db["sale_transactions"].aggregate([
            {"$match": sale_match},
            {"$group": {"_id": None,
                "revenue": {"$sum": "$sellingPrice"},
                "profit":  {"$sum": "$profit"},
                "count":   {"$sum": 1}}},
        ]).to_list(1)
        e_agg = await db["expense_records"].aggregate([
            {"$match": exp_match},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
        ]).to_list(1)
        sd = s_agg[0] if s_agg else {}
        stats = {
            "totalRevenue":   sd.get("revenue", 0),
            "totalProfit":    sd.get("profit",  0),
            "totalExpenses":  e_agg[0]["total"] if e_agg else 0,
            "totalSales":     sd.get("count",   0),
            "soldCars":       sd.get("count",   0),
            "totalCars":      await db["car_listings"].count_documents({"dealerId": did}),
            "totalStaff":     await db["staff_accounts"].count_documents({"dealerId": did}),
            "totalNetProfit": sd.get("profit", 0) - (e_agg[0]["total"] if e_agg else 0),
        }
    else:
        stats = await get_dealer_stats_full(did)

    return {
        "summary":             stats,
        "monthlySales":        monthly,
        "topBrands":           [{"brand": b["_id"] or "Unknown", "count": b["count"], "revenue": b["revenue"]} for b in top_brands],
        "paymentBreakdown":    [{"method": p["_id"] or "cash",   "count": p["count"], "total":   p["total"]}   for p in payment_breakdown],
        "staffPerformance":    staff_perf,
        "expensesByCategory":  [{"category": e["_id"] or "other","total": e["total"], "count": e["count"]}     for e in expenses_by_cat],
    }