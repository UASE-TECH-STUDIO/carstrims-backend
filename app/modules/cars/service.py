from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException, status
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc
import random
import string


def generate_car_id():
    chars = string.ascii_uppercase + string.digits
    return "CAR-" + "".join(random.choices(chars, k=8))


async def create_car(dealer_id: str, user_id: str, data: dict) -> dict:
    db = get_db()
    from bson import ObjectId as _OID

    # Look up dealer by the dealer_id passed in (works for both dealer admin and staff)
    dealer = None
    if _OID.is_valid(str(dealer_id)):
        dealer = await db["dealer_organizations"].find_one({"_id": _OID(str(dealer_id))})
    if not dealer:
        dealer = await db["dealer_organizations"].find_one({"dealerId": str(dealer_id)})
    if not dealer:
        # Final fallback: try by userId (only works for dealer admin)
        dealer = await db["dealer_organizations"].find_one({"userId": user_id})
    if not dealer:
        raise HTTPException(status_code=404, detail="Dealer profile not found")

    purchase_price = data.get("purchasePrice") or 0
    selling_price = data.get("sellingPrice", 0)
    estimated_profit = selling_price - purchase_price

    car_doc = {
        "carId": generate_car_id(),
        "dealerId": str(dealer["_id"]),
        "dealerDealerId": dealer.get("dealerId"),
        "ownerId": data.get("ownerId", str(dealer["_id"])),
        "ownerType": data.get("ownerType", "dealer"),
        "vehicleType": data.get("vehicleType") or "car",
        "brand": data.get("brand"),
        "model": data.get("model"),
        "year": data.get("year"),
        "color": data.get("color"),
        "mileage": data.get("mileage"),
        "vin": data.get("vin"),
        "engineType": data.get("engineType"),
        "transmission": data.get("transmission"),
        "fuelType": data.get("fuelType"),
        "condition": data.get("condition", "used"),
        "description": data.get("description"),
        "state": data.get("state"),
        "city": data.get("city"),
        "purchasePrice": purchase_price,
        "sellingPrice": selling_price,
        "promoPrice": data.get("promoPrice"),
        "minNegotiationPrice": data.get("minNegotiationPrice"),
        "estimatedProfit": estimated_profit,
        "actualProfit": None,
        "status": "available",
        "images": [],
        "video": None,
        "qrCode": None,
        "viewCount": 0,
        "likeCount": 0,
        "isFeatured": False,
        "soldAt": None,
        "soldBy": None,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    result = await db["car_listings"].insert_one(car_doc)
    car_doc["_id"] = result.inserted_id

    await db["dealer_organizations"].update_one(
        {"_id": dealer["_id"]},
        {"$inc": {"totalCarsListed": 1}},
    )

    return serialize_doc(car_doc)


async def get_dealer_cars(
    dealer_id: str,
    status_filter: str = None,
    search: str = None,
    skip: int = 0,
    limit: int = 20,
) -> dict:
    db = get_db()

    query = {"dealerId": dealer_id}
    if status_filter:
        query["status"] = status_filter
    if search:
        query["$or"] = [
            {"brand": {"$regex": search, "$options": "i"}},
            {"model": {"$regex": search, "$options": "i"}},
            {"carId": {"$regex": search, "$options": "i"}},
            {"color": {"$regex": search, "$options": "i"}},
            {"vin": {"$regex": search, "$options": "i"}},
        ]

    total = await db["car_listings"].count_documents(query)
    cars = await db["car_listings"].find(query).sort(
        "createdAt", -1
    ).skip(skip).limit(limit).to_list(limit)

    return {
        "total": total,
        "cars": [serialize_doc(c) for c in cars],
        "skip": skip,
        "limit": limit,
    }


async def get_car_by_id(car_id: str, dealer_id: str = None) -> dict:
    db = get_db()

    if ObjectId.is_valid(car_id):
        query = {"_id": ObjectId(car_id)}
    else:
        query = {"carId": car_id}

    if dealer_id:
        query["dealerId"] = dealer_id

    car = await db["car_listings"].find_one(query)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    return serialize_doc(car)


async def update_car(car_id: str, dealer_id: str, data: dict) -> dict:
    db = get_db()

    if ObjectId.is_valid(car_id):
        query = {"_id": ObjectId(car_id), "dealerId": dealer_id}
    else:
        query = {"carId": car_id, "dealerId": dealer_id}

    car = await db["car_listings"].find_one(query)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    data.pop("_id", None)
    data.pop("carId", None)
    data.pop("dealerId", None)
    data["updatedAt"] = datetime.utcnow()

    if "purchasePrice" in data or "sellingPrice" in data:
        purchase = data["purchasePrice"] if data.get("purchasePrice") is not None else (car.get("purchasePrice") or 0)
        selling = data["sellingPrice"] if data.get("sellingPrice") is not None else (car.get("sellingPrice") or 0)
        data["estimatedProfit"] = selling - purchase

    await db["car_listings"].update_one(query, {"$set": data})
    return await get_car_by_id(str(car["_id"]))


async def mark_car_sold(
    car_id: str,
    dealer_id: str,
    selling_price: float,
    buyer_name: str = None,
    buyer_phone: str = None,
    payment_method: str = "cash",
    staff_id: str = None,
    notes: str = None,
) -> dict:
    db = get_db()

    if ObjectId.is_valid(car_id):
        query = {"_id": ObjectId(car_id), "dealerId": dealer_id}
    else:
        query = {"carId": car_id, "dealerId": dealer_id}

    car = await db["car_listings"].find_one(query)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    if car["status"] == "sold":
        raise HTTPException(status_code=400, detail="Car is already sold")

    expenses_result = await db["expense_records"].aggregate([
        {"$match": {"carId": car.get("carId"), "dealerId": dealer_id}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_expenses = expenses_result[0]["total"] if expenses_result else 0

    profit = selling_price - (car.get("purchasePrice") or 0)
    net_profit = profit - total_expenses

    trans_id = "TXN-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))

    sale_doc = {
        "transactionId": trans_id,
        "carId": car.get("carId"),
        "carMongoId": str(car["_id"]),
        "dealerId": dealer_id,
        "staffId": staff_id,
        "sellingPrice": selling_price,
        "purchasePrice": car.get("purchasePrice") or 0,
        "profit": profit,
        "expenses": total_expenses,
        "netProfit": net_profit,
        "paymentMethod": payment_method,
        "buyerName": buyer_name,
        "buyerPhone": buyer_phone,
        "notes": notes,
        "partnerId": car.get("ownerId") if car.get("ownerType") == "partner" else None,
        "soldAt": datetime.utcnow(),
        "createdAt": datetime.utcnow(),
    }

    await db["sale_transactions"].insert_one(sale_doc)

    await db["car_listings"].update_one(
        {"_id": car["_id"]},
        {"$set": {
            "status": "sold",
            "actualProfit": net_profit,
            "soldAt": datetime.utcnow(),
            "soldBy": staff_id,
            "sellingPrice": selling_price,
            "updatedAt": datetime.utcnow(),
        }},
    )

    await db["dealer_organizations"].update_one(
        {"_id": ObjectId(dealer_id)},
        {"$inc": {
            "totalCarsSold": 1,
            "totalRevenue": selling_price,
        }},
    )

    await db["notifications"].insert_one({
        "receiverId": car.get("ownerId"),
        "dealerId": dealer_id,
        "type": "car_sold",
        "title": "Car Sold!",
        "message": f"{car.get('brand')} {car.get('model')} {car.get('year')} has been sold for {selling_price:,.0f}",
        "isRead": False,
        "data": {"transactionId": trans_id, "carId": car.get("carId")},
        "createdAt": datetime.utcnow(),
    })

    return {
        "message": "Car marked as sold",
        "transactionId": trans_id,
        "profit": profit,
        "netProfit": net_profit,
        "carId": car.get("carId"),
    }


async def delete_car(car_id: str, dealer_id: str) -> dict:
    db = get_db()

    if ObjectId.is_valid(car_id):
        query = {"_id": ObjectId(car_id), "dealerId": dealer_id}
    else:
        query = {"carId": car_id, "dealerId": dealer_id}

    car = await db["car_listings"].find_one(query)
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    if car["status"] == "sold":
        raise HTTPException(status_code=400, detail="Cannot delete a sold car")

    await db["car_listings"].delete_one({"_id": car["_id"]})

    await db["dealer_organizations"].update_one(
        {"_id": ObjectId(dealer_id)},
        {"$inc": {"totalCarsListed": -1}},
    )

    return {"message": "Car deleted successfully", "carId": car.get("carId")}


async def get_public_cars(
    search: str = None,
    brand: str = None,
    min_price: float = None,
    max_price: float = None,
    city: str = None,
    skip: int = 0,
    limit: int = 20,
) -> dict:
    db = get_db()

    query = {"status": "available"}
    if search:
        query["$or"] = [
            {"brand": {"$regex": search, "$options": "i"}},
            {"model": {"$regex": search, "$options": "i"}},
        ]
    if brand:
        query["brand"] = {"$regex": brand, "$options": "i"}
    if min_price is not None:
        query.setdefault("sellingPrice", {})["$gte"] = min_price
    if max_price is not None:
        query.setdefault("sellingPrice", {})["$lte"] = max_price
    if city:
        query["city"] = {"$regex": city, "$options": "i"}

    total = await db["car_listings"].count_documents(query)
    cars = await db["car_listings"].find(query).sort(
        "createdAt", -1
    ).skip(skip).limit(limit).to_list(limit)

    return {
        "total": total,
        "cars": [serialize_doc(c) for c in cars],
        "skip": skip,
        "limit": limit,
    }
