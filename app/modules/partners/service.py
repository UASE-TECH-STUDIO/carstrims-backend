from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc


async def send_partner_request(user_id: str, dealer_id: str) -> dict:
    db = get_db()

    dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer not found")

    existing = await db["partner_links"].find_one({
        "userId": user_id, "dealerId": dealer_id,
    })
    if existing:
        raise HTTPException(status_code=400, detail="Partner request already exists")

    link_doc = {
        "userId": user_id,
        "dealerId": dealer_id,
        "status": "pending",
        "carIds": [],
        "totalCarsAssigned": 0,
        "totalCarsSold": 0,
        "totalRevenue": 0.0,
        "totalPendingPayment": 0.0,
        "revenueSharePercent": None,
        "requestedAt": datetime.utcnow(),
        "approvedAt": None,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    result = await db["partner_links"].insert_one(link_doc)
    link_doc["_id"] = result.inserted_id

    await db["notifications"].insert_one({
        "receiverId": dealer["userId"],
        "senderId": user_id,
        "type": "partner_request",
        "title": "New Partner Request",
        "message": "A new partner wants to link with your dealership.",
        "isRead": False,
        "data": {"linkId": str(result.inserted_id)},
        "createdAt": datetime.utcnow(),
    })

    return serialize_doc(link_doc)


async def get_dealer_partners(
    dealer_id: str,
    status_filter: str = None,
    skip: int = 0,
    limit: int = 20,
) -> dict:
    db = get_db()

    query = {"dealerId": dealer_id}
    if status_filter:
        query["status"] = status_filter

    total = await db["partner_links"].count_documents(query)
    links = await db["partner_links"].find(query).sort(
        "createdAt", -1
    ).skip(skip).limit(limit).to_list(limit)

    enriched = []
    for link in links:
        serialized = serialize_doc(link)
        user = await db["users"].find_one({"_id": ObjectId(link["userId"])})
        if user:
            serialized["partnerInfo"] = {
                "fullName": user.get("fullName"),
                "email": user.get("email"),
                "phone": user.get("phone"),
                "profilePicture": user.get("profilePicture"),
            }
        enriched.append(serialized)

    return {"total": total, "partners": enriched, "skip": skip, "limit": limit}


async def approve_partner(link_id: str, dealer_id: str) -> dict:
    db = get_db()

    link = await db["partner_links"].find_one({
        "_id": ObjectId(link_id), "dealerId": dealer_id,
    })
    if not link:
        raise HTTPException(status_code=404, detail="Partner request not found")

    await db["partner_links"].update_one(
        {"_id": link["_id"]},
        {"$set": {
            "status": "approved",
            "approvedAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
        }},
    )

    await db["users"].update_one(
        {"_id": ObjectId(link["userId"])},
        {"$set": {"role": "PARTNER_USER", "updatedAt": datetime.utcnow()}},
    )

    dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})

    await db["notifications"].insert_one({
        "receiverId": link["userId"],
        "senderId": dealer.get("userId") if dealer else None,
        "type": "partner_request",
        "title": "Partner Request Approved",
        "message": f"Your partnership request has been approved. Welcome aboard!",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    return {"message": "Partner approved successfully"}


async def reject_partner(link_id: str, dealer_id: str, reason: str = None) -> dict:
    db = get_db()

    link = await db["partner_links"].find_one({
        "_id": ObjectId(link_id), "dealerId": dealer_id,
    })
    if not link:
        raise HTTPException(status_code=404, detail="Partner request not found")

    await db["partner_links"].update_one(
        {"_id": link["_id"]},
        {"$set": {
            "status": "rejected",
            "updatedAt": datetime.utcnow(),
        }},
    )

    return {"message": "Partner request rejected"}


async def assign_car_to_partner(
    link_id: str, dealer_id: str, car_id: str
) -> dict:
    db = get_db()

    link = await db["partner_links"].find_one({
        "_id": ObjectId(link_id), "dealerId": dealer_id, "status": "approved",
    })
    if not link:
        raise HTTPException(status_code=404, detail="Active partner link not found")

    car = await db["car_listings"].find_one({"carId": car_id, "dealerId": dealer_id})
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    await db["partner_links"].update_one(
        {"_id": link["_id"]},
        {
            "$addToSet": {"carIds": car_id},
            "$inc": {"totalCarsAssigned": 1},
            "$set": {"updatedAt": datetime.utcnow()},
        },
    )

    await db["car_listings"].update_one(
        {"carId": car_id},
        {"$set": {
            "ownerId": link["userId"],
            "ownerType": "partner",
            "updatedAt": datetime.utcnow(),
        }},
    )

    return {"message": "Car assigned to partner successfully"}


async def get_partner_dashboard(user_id: str) -> dict:
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
        ).to_list(100)
        cars = [serialize_doc(c) for c in car_docs]

    total_revenue = sum(
        c.get("sellingPrice", 0) for c in cars if c.get("status") == "sold"
    )

    dealer_ids = [link["dealerId"] for link in links]
    dealers = []
    for did in dealer_ids:
        d = await db["dealer_organizations"].find_one({"_id": ObjectId(did)})
        if d:
            dealers.append(serialize_doc(d))

    return {
        "totalLinkedDealers": len(links),
        "totalCarsAssigned": len(all_car_ids),
        "totalCarsSold": sum(1 for c in cars if c.get("status") == "sold"),
        "totalRevenue": total_revenue,
        "cars": cars,
        "dealers": dealers,
    }


async def remove_partner(link_id: str, dealer_id: str) -> dict:
    db = get_db()

    link = await db["partner_links"].find_one({
        "_id": ObjectId(link_id), "dealerId": dealer_id,
    })
    if not link:
        raise HTTPException(status_code=404, detail="Partner link not found")

    await db["partner_links"].update_one(
        {"_id": link["_id"]},
        {"$set": {"status": "suspended", "updatedAt": datetime.utcnow()}},
    )

    return {"message": "Partner removed from dealership"}
