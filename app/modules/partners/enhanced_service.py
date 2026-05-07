from datetime import datetime
from bson import ObjectId
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc


async def get_partner_full_dashboard(user_id: str) -> dict:
    db = get_db()

    links = await db["partner_links"].find(
        {"userId": user_id, "status": "approved"}
    ).to_list(100)

    all_car_ids = []
    for link in links:
        all_car_ids.extend(link.get("carIds", []))

    cars = []
    if all_car_ids:
        car_docs = await db["car_listings"].find(
            {"carId": {"$in": all_car_ids}}
        ).sort("createdAt", -1).to_list(200)
        for c in car_docs:
            s = serialize_doc(c)
            dealer = await db["dealer_organizations"].find_one(
                {"_id": ObjectId(c["dealerId"])}
            ) if ObjectId.is_valid(c.get("dealerId", "")) else None
            s["dealerName"] = dealer.get("companyName") if dealer else "—"
            cars.append(s)

    dealers = []
    for link in links:
        d = await db["dealer_organizations"].find_one({"_id": ObjectId(link["dealerId"])})
        if d:
            s = serialize_doc(d)
            s["linkId"] = str(link["_id"])
            s["linkStatus"] = link.get("status")
            s["carsAssigned"] = len(link.get("carIds", []))
            dealers.append(s)

    sold_cars = [c for c in cars if c.get("status") == "sold"]
    total_revenue = sum(c.get("sellingPrice", 0) for c in sold_cars)
    total_profit = sum(c.get("actualProfit") or c.get("estimatedProfit", 0) for c in sold_cars)

    movements = await db["vehicle_movement_logs"].find(
        {"carId": {"$in": all_car_ids}}
    ).sort("createdAt", -1).limit(20).to_list(20)

    return {
        "totalLinkedDealers": len(links),
        "totalCarsAssigned": len(all_car_ids),
        "totalCarsSold": len(sold_cars),
        "totalCarsAvailable": len([c for c in cars if c.get("status") == "available"]),
        "totalRevenue": total_revenue,
        "totalProfit": total_profit,
        "cars": cars,
        "dealers": dealers,
        "recentMovements": [serialize_doc(m) for m in movements],
    }


async def get_partner_earnings(user_id: str) -> dict:
    db = get_db()
    links = await db["partner_links"].find({"userId": user_id}).to_list(100)

    all_car_ids = []
    for link in links:
        all_car_ids.extend(link.get("carIds", []))

    sales = await db["sale_transactions"].find(
        {"carId": {"$in": all_car_ids}}
    ).sort("soldAt", -1).to_list(100)

    monthly = {}
    for s in sales:
        sold_at = s.get("soldAt")
        if sold_at:
            key = sold_at.strftime("%b %Y") if hasattr(sold_at, "strftime") else str(sold_at)[:7]
            if key not in monthly:
                monthly[key] = {"month": key, "revenue": 0, "count": 0}
            monthly[key]["revenue"] += s.get("sellingPrice", 0)
            monthly[key]["count"] += 1

    return {
        "totalSales": len(sales),
        "totalRevenue": sum(s.get("sellingPrice", 0) for s in sales),
        "monthlySales": list(monthly.values())[-6:],
        "recentSales": [serialize_doc(s) for s in sales[:10]],
    }
