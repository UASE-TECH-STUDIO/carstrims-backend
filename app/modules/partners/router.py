from fastapi import APIRouter, Depends, Query, Body
from typing import Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_user, get_current_dealer, get_current_dealer_or_staff
from app.modules.dealers.service import get_dealer_by_user_id, serialize_doc
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime
import random, string


class PartnerRequestCreate(BaseModel):
    dealerId: str


class PartnerActionRequest(BaseModel):
    reason: Optional[str] = None


class AssignCarRequest(BaseModel):
    carId: str


router = APIRouter(prefix="/api/v1/partners", tags=["Partners"])


def gen_link_id():
    return "LNK-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


@router.post("/request")
async def send_partner_request(
    data: PartnerRequestCreate,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    dealer_id = data.dealerId

    if ObjectId.is_valid(dealer_id):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    else:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})

    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")

    dealer_mongo_id = str(dealer["_id"])
    user_id = str(current_user["_id"])

    existing = await db["partner_links"].find_one({
        "userId": user_id,
        "dealerId": dealer_mongo_id,
    })
    if existing:
        from fastapi import HTTPException
        status = existing.get("status", "pending")
        raise HTTPException(
            status_code=400,
            detail=f"You already have a {status} partnership with this dealer"
        )

    link_doc = {
        "linkId": gen_link_id(),
        "userId": user_id,
        "dealerId": dealer_mongo_id,
        "partnerName": current_user.get("fullName", ""),
        "partnerEmail": current_user.get("email", ""),
        "partnerPhone": current_user.get("phone", ""),
        "status": "pending",
        "carIds": [],
        "requestedAt": datetime.utcnow(),
        "approvedAt": None,
        "createdAt": datetime.utcnow(),
    }

    await db["partner_links"].insert_one(link_doc)

    await db["notifications"].insert_one({
        "receiverId": dealer["userId"],
        "senderId": user_id,
        "type": "partner_request",
        "title": "New Partnership Request",
        "message": f"{current_user.get('fullName','A user')} wants to partner with your dealership",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    return {"message": "Partnership request sent successfully", "linkId": link_doc["linkId"]}


@router.get("/my-links")
async def get_my_links(current_user: dict = Depends(get_current_user)):
    db = get_db()
    links = await db["partner_links"].find(
        {"userId": str(current_user["_id"])}
    ).sort("createdAt", -1).to_list(100)

    result = []
    for link in links:
        s = serialize_doc(link)
        dealer = await db["dealer_organizations"].find_one(
            {"_id": ObjectId(link["dealerId"])}
        ) if ObjectId.is_valid(link["dealerId"]) else None
        if dealer:
            s["dealerName"] = dealer.get("companyName")
            s["dealerLogo"] = dealer.get("logo")
            s["dealerCity"] = dealer.get("city")
            s["dealerState"] = dealer.get("state")
            s["dealerPhone"] = dealer.get("phone")
            s["dealerWhatsapp"] = dealer.get("whatsapp")
            s["dealerEmail"] = dealer.get("email")
            s["dealerDealerId"] = dealer.get("dealerId")
        result.append(s)
    return result


@router.get("/my-dashboard")
async def partner_dashboard(current_user: dict = Depends(get_current_user)):
    db = get_db()
    user_id = str(current_user["_id"])

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
            if c.get("dealerId") and ObjectId.is_valid(c["dealerId"]):
                dealer = await db["dealer_organizations"].find_one(
                    {"_id": ObjectId(c["dealerId"])}
                )
                s["dealerName"] = dealer.get("companyName") if dealer else ""
                s["dealerLogo"] = dealer.get("logo") if dealer else None
            cars.append(s)

    dealers = []
    for link in links:
        if ObjectId.is_valid(link["dealerId"]):
            d = await db["dealer_organizations"].find_one({"_id": ObjectId(link["dealerId"])})
            if d:
                s = serialize_doc(d)
                s["linkId"] = str(link["_id"])
                s["linkStatus"] = link.get("status")
                s["carsAssigned"] = len(link.get("carIds", []))
                dealers.append(s)

    sold_cars = [c for c in cars if c.get("status") == "sold"]
    total_revenue = sum(c.get("sellingPrice", 0) for c in sold_cars)

    movements = await db["vehicle_movement_logs"].find(
        {"carId": {"$in": all_car_ids}}
    ).sort("createdAt", -1).limit(20).to_list(20) if all_car_ids else []

    return {
        "totalLinkedDealers": len(links),
        "totalCarsAssigned": len(all_car_ids),
        "totalCarsSold": len(sold_cars),
        "totalCarsAvailable": len([c for c in cars if c.get("status") == "available"]),
        "totalRevenue": total_revenue,
        "cars": cars,
        "dealers": dealers,
        "recentMovements": [serialize_doc(m) for m in movements],
    }


@router.get("/my-earnings")
async def partner_earnings(current_user: dict = Depends(get_current_user)):
    db = get_db()
    links = await db["partner_links"].find({"userId": str(current_user["_id"])}).to_list(100)
    all_car_ids = []
    for link in links:
        all_car_ids.extend(link.get("carIds", []))

    sales = await db["sale_transactions"].find(
        {"carId": {"$in": all_car_ids}}
    ).sort("soldAt", -1).to_list(100) if all_car_ids else []

    monthly: dict = {}
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


@router.get("/")
async def list_dealer_partners(
    status: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(20),
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    query = {"dealerId": dealer["_id"]}
    if status:
        query["status"] = status

    total = await db["partner_links"].count_documents(query)
    links = await db["partner_links"].find(query).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)

    result = []
    for link in links:
        s = serialize_doc(link)
        user = await db["users"].find_one({"_id": ObjectId(link["userId"])})
        if user:
            s["partnerName"] = user.get("fullName")
            s["partnerEmail"] = user.get("email")
            s["partnerPhone"] = user.get("phone")
        result.append(s)

    return {"total": total, "partners": result}


@router.get("/{link_id}/detail")
async def partner_detail(link_id: str, current_user: dict = Depends(get_current_dealer_or_staff)):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)

    if ObjectId.is_valid(link_id):
        link = await db["partner_links"].find_one({"_id": ObjectId(link_id)})
    else:
        link = await db["partner_links"].find_one({"linkId": link_id})

    if not link:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Partner link not found")

    partner_user = await db["users"].find_one({"_id": ObjectId(link["userId"])})
    car_ids = link.get("carIds", [])

    cars = []
    if car_ids:
        car_docs = await db["car_listings"].find({"carId": {"$in": car_ids}}).to_list(100)
        for c in car_docs:
            s = serialize_doc(c)
            expenses = await db["expense_records"].find({"carId": c["carId"]}).to_list(50)
            s["totalExpenses"] = sum(e.get("amount", 0) for e in expenses)
            sales_docs = await db["sale_transactions"].find({"carId": c["carId"]}).to_list(5)
            s["saleRecord"] = serialize_doc(sales_docs[0]) if sales_docs else None
            cars.append(s)

    agg = [
        {"$match": {"carId": {"$in": car_ids}}},
        {"$group": {"_id": None, "total": {"$sum": "$sellingPrice"}, "profit": {"$sum": "$profit"}, "count": {"$sum": 1}}},
    ]
    sales_agg = await db["sale_transactions"].aggregate(agg).to_list(1) if car_ids else []
    sales_summary = sales_agg[0] if sales_agg else {"total": 0, "profit": 0, "count": 0}

    movements = await db["vehicle_movement_logs"].find(
        {"carId": {"$in": car_ids}}
    ).sort("createdAt", -1).limit(20).to_list(20) if car_ids else []

    return {
        "link": serialize_doc(link),
        "partner": serialize_doc(partner_user) if partner_user else None,
        "cars": cars,
        "totalCars": len(car_ids),
        "carsSold": len([c for c in cars if c.get("status") == "sold"]),
        "carsAvailable": len([c for c in cars if c.get("status") == "available"]),
        "totalRevenue": sales_summary.get("total", 0),
        "totalProfit": sales_summary.get("profit", 0),
        "totalSales": sales_summary.get("count", 0),
        "recentMovements": [serialize_doc(m) for m in movements],
    }


@router.post("/{link_id}/approve")
async def approve_partner(link_id: str, current_user: dict = Depends(get_current_dealer_or_staff)):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)

    if ObjectId.is_valid(link_id):
        query = {"_id": ObjectId(link_id), "dealerId": dealer["_id"]}
    else:
        query = {"linkId": link_id, "dealerId": dealer["_id"]}

    link = await db["partner_links"].find_one(query)
    if not link:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Link not found")

    await db["partner_links"].update_one(
        {"_id": link["_id"]},
        {"$set": {"status": "approved", "approvedAt": datetime.utcnow()}},
    )

    await db["notifications"].insert_one({
        "receiverId": link["userId"],
        "type": "partner_request",
        "title": "Partnership Approved!",
        "message": "Your partnership request has been approved. You are now linked with the dealer.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    # Fire push notification
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(
            link["userId"],
            "Partnership Approved!",
            "Your partnership request has been approved. You are now linked with the dealer.",
            "/dashboard",
        ))
    except Exception as _pe:
        pass

    return {"message": "Partner approved"}


@router.post("/{link_id}/reject")
async def reject_partner(
    link_id: str,
    data: PartnerActionRequest,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)

    if ObjectId.is_valid(link_id):
        query = {"_id": ObjectId(link_id), "dealerId": dealer["_id"]}
    else:
        query = {"linkId": link_id, "dealerId": dealer["_id"]}

    link = await db["partner_links"].find_one(query)
    if not link:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Link not found")

    await db["partner_links"].update_one(
        {"_id": link["_id"]},
        {"$set": {"status": "rejected", "rejectedAt": datetime.utcnow()}},
    )

    await db["notifications"].insert_one({
        "receiverId": link["userId"],
        "type": "general",
        "title": "Partnership Request Declined",
        "message": data.reason or "Your partnership request was declined.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    # Fire push notification
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(
            link["userId"],
            "Partnership Request Declined",
            data.reason or "Your partnership request was declined.",
            "/dashboard",
        ))
    except Exception as _pe:
        pass

    return {"message": "Partner rejected"}


@router.post("/{link_id}/assign-car")
async def assign_car(
    link_id: str,
    data: AssignCarRequest,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)

    if ObjectId.is_valid(link_id):
        query = {"_id": ObjectId(link_id), "dealerId": dealer["_id"]}
    else:
        query = {"linkId": link_id, "dealerId": dealer["_id"]}

    link = await db["partner_links"].find_one(query)
    if not link:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Link not found")

    if data.carId not in link.get("carIds", []):
        await db["partner_links"].update_one(
            {"_id": link["_id"]},
            {"$push": {"carIds": data.carId}},
        )

    return {"message": "Car assigned to partner"}


@router.delete("/{link_id}")
async def remove_partner(link_id: str, current_user: dict = Depends(get_current_dealer_or_staff)):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)

    if ObjectId.is_valid(link_id):
        query = {"_id": ObjectId(link_id), "dealerId": dealer["_id"]}
    else:
        query = {"linkId": link_id, "dealerId": dealer["_id"]}

    await db["partner_links"].delete_one(query)
    return {"message": "Partner removed"}