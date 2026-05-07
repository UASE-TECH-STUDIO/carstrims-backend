from datetime import datetime, timedelta
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc


async def get_dealer_reports(dealer_id: str, period: str = "month") -> dict:
    db = get_db()

    now = datetime.utcnow()
    if period == "week":
        start_date = now - timedelta(days=7)
    elif period == "year":
        start_date = now - timedelta(days=365)
    else:
        start_date = now - timedelta(days=30)

    # Sales summary
    sales_pipeline = [
        {"$match": {"dealerId": dealer_id, "soldAt": {"$gte": start_date}}},
        {"$group": {
            "_id": None,
            "totalSales": {"$sum": 1},
            "totalRevenue": {"$sum": "$sellingPrice"},
            "totalProfit": {"$sum": "$profit"},
            "totalNetProfit": {"$sum": "$netProfit"},
            "totalExpenses": {"$sum": "$expenses"},
        }},
    ]
    sales_result = await db["sale_transactions"].aggregate(sales_pipeline).to_list(1)
    sales_summary = sales_result[0] if sales_result else {
        "totalSales": 0, "totalRevenue": 0,
        "totalProfit": 0, "totalNetProfit": 0, "totalExpenses": 0,
    }
    sales_summary.pop("_id", None)

    # Sales by day for chart
    daily_pipeline = [
        {"$match": {"dealerId": dealer_id, "soldAt": {"$gte": start_date}}},
        {"$group": {
            "_id": {
                "year": {"$year": "$soldAt"},
                "month": {"$month": "$soldAt"},
                "day": {"$dayOfMonth": "$soldAt"},
            },
            "sales": {"$sum": 1},
            "revenue": {"$sum": "$sellingPrice"},
            "profit": {"$sum": "$profit"},
        }},
        {"$sort": {"_id.year": 1, "_id.month": 1, "_id.day": 1}},
    ]
    daily_data = await db["sale_transactions"].aggregate(daily_pipeline).to_list(100)
    daily_chart = [
        {
            "date": f"{d['_id']['year']}-{str(d['_id']['month']).zfill(2)}-{str(d['_id']['day']).zfill(2)}",
            "sales": d["sales"],
            "revenue": d["revenue"],
            "profit": d["profit"],
        }
        for d in daily_data
    ]

    # Top selling brands
    brand_pipeline = [
        {"$match": {"dealerId": dealer_id, "soldAt": {"$gte": start_date}}},
        {"$lookup": {
            "from": "car_listings",
            "localField": "carMongoId",
            "foreignField": "_id",
            "as": "car",
        }},
        {"$unwind": {"path": "$car", "preserveNullAndEmptyArrays": True}},
        {"$group": {
            "_id": "$car.brand",
            "count": {"$sum": 1},
            "revenue": {"$sum": "$sellingPrice"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    brand_data = await db["sale_transactions"].aggregate(brand_pipeline).to_list(5)
    top_brands = [
        {"brand": b["_id"] or "Unknown", "count": b["count"], "revenue": b["revenue"]}
        for b in brand_data
    ]

    # Payment methods breakdown
    payment_pipeline = [
        {"$match": {"dealerId": dealer_id, "soldAt": {"$gte": start_date}}},
        {"$group": {
            "_id": "$paymentMethod",
            "count": {"$sum": 1},
            "total": {"$sum": "$sellingPrice"},
        }},
    ]
    payment_data = await db["sale_transactions"].aggregate(payment_pipeline).to_list(10)
    payment_breakdown = [
        {"method": p["_id"] or "cash", "count": p["count"], "total": p["total"]}
        for p in payment_data
    ]

    # Staff performance
    staff_pipeline = [
        {"$match": {"dealerId": dealer_id, "soldAt": {"$gte": start_date}, "staffId": {"$ne": None}}},
        {"$group": {
            "_id": "$staffId",
            "salesCount": {"$sum": 1},
            "totalRevenue": {"$sum": "$sellingPrice"},
        }},
        {"$sort": {"salesCount": -1}},
        {"$limit": 5},
    ]
    staff_data = await db["sale_transactions"].aggregate(staff_pipeline).to_list(5)

    staff_performance = []
    for s in staff_data:
        staff_member = await db["staff_accounts"].find_one({"userId": s["_id"]})
        staff_performance.append({
            "staffId": s["_id"],
            "name": staff_member.get("fullName", "Unknown") if staff_member else "Unknown",
            "salesCount": s["salesCount"],
            "totalRevenue": s["totalRevenue"],
        })

    # Inventory summary
    total_cars = await db["car_listings"].count_documents({"dealerId": dealer_id})
    available = await db["car_listings"].count_documents({"dealerId": dealer_id, "status": "available"})
    sold = await db["car_listings"].count_documents({"dealerId": dealer_id, "status": "sold"})
    in_repair = await db["car_listings"].count_documents({"dealerId": dealer_id, "status": "in_repair"})

    # Recent transactions
    recent_sales = await db["sale_transactions"].find(
        {"dealerId": dealer_id}
    ).sort("soldAt", -1).limit(10).to_list(10)

    return {
        "period": period,
        "generatedAt": now.isoformat(),
        "salesSummary": sales_summary,
        "dailyChart": daily_chart,
        "topBrands": top_brands,
        "paymentBreakdown": payment_breakdown,
        "staffPerformance": staff_performance,
        "inventorySummary": {
            "total": total_cars,
            "available": available,
            "sold": sold,
            "inRepair": in_repair,
        },
        "recentSales": [serialize_doc(s) for s in recent_sales],
    }


async def get_admin_platform_reports() -> dict:
    db = get_db()

    total_dealers = await db["dealer_organizations"].count_documents({})
    approved_dealers = await db["dealer_organizations"].count_documents({"status": "approved"})
    pending_dealers = await db["dealer_organizations"].count_documents({"status": "awaiting_approval"})
    suspended_dealers = await db["dealer_organizations"].count_documents({"status": "suspended"})
    total_cars = await db["car_listings"].count_documents({})
    total_sold = await db["car_listings"].count_documents({"status": "sold"})
    total_users = await db["users"].count_documents({})

    revenue_pipeline = [
        {"$group": {"_id": None, "total": {"$sum": "$sellingPrice"}}},
    ]
    rev = await db["sale_transactions"].aggregate(revenue_pipeline).to_list(1)
    total_platform_revenue = rev[0]["total"] if rev else 0

    top_dealers_pipeline = [
        {"$match": {"status": "approved"}},
        {"$sort": {"totalCarsSold": -1}},
        {"$limit": 10},
    ]
    top_dealers = await db["dealer_organizations"].aggregate(top_dealers_pipeline).to_list(10)

    return {
        "totalDealers": total_dealers,
        "approvedDealers": approved_dealers,
        "pendingDealers": pending_dealers,
        "suspendedDealers": suspended_dealers,
        "totalCars": total_cars,
        "totalSold": total_sold,
        "totalUsers": total_users,
        "totalPlatformRevenue": total_platform_revenue,
        "topDealers": [serialize_doc(d) for d in top_dealers],
    }
