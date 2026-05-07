from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc
import random
import string


def generate_movement_id():
    return "MOV-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


async def log_movement(dealer_id: str, data: dict) -> dict:
    db = get_db()

    car = await db["car_listings"].find_one({
        "carId": data.get("carId"), "dealerId": dealer_id,
    })
    if not car:
        raise HTTPException(status_code=404, detail="Car not found in your inventory")

    if car["status"] == "sold":
        raise HTTPException(status_code=400, detail="Cannot log movement for a sold car")

    movement_doc = {
        "movementId": generate_movement_id(),
        "dealerId": dealer_id,
        "carId": data.get("carId"),
        "carBrand": car.get("brand"),
        "carModel": car.get("model"),
        "carYear": car.get("year"),
        "takenByName": data.get("takenByName"),
        "takenByPhone": data.get("takenByPhone"),
        "idCardUrl": data.get("idCardUrl"),
        "purpose": data.get("purpose", "other"),
        "staffReleasedId": data.get("staffReleasedId"),
        "approvedById": data.get("approvedById"),
        "expectedReturnTime": data.get("expectedReturnTime"),
        "keyLocation": data.get("keyLocation"),
        "notes": data.get("notes"),
        "status": "out",
        "timeOut": datetime.utcnow(),
        "timeReturned": None,
        "staffReceivedId": None,
        "conditionOnReturn": None,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    result = await db["vehicle_movement_logs"].insert_one(movement_doc)
    movement_doc["_id"] = result.inserted_id

    await db["car_listings"].update_one(
        {"carId": data.get("carId"), "dealerId": dealer_id},
        {"$set": {"status": "out_for_inspection", "updatedAt": datetime.utcnow()}},
    )

    await db["notifications"].insert_one({
        "receiverId": dealer_id,
        "type": "car_moved",
        "title": "Vehicle Movement Logged",
        "message": f"{car.get('brand')} {car.get('model')} taken by {data.get('takenByName')} for {data.get('purpose')}",
        "isRead": False,
        "data": {"movementId": movement_doc["movementId"]},
        "createdAt": datetime.utcnow(),
    })

    return serialize_doc(movement_doc)


async def get_movements(
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
            {"carId": {"$regex": search, "$options": "i"}},
            {"takenByName": {"$regex": search, "$options": "i"}},
            {"movementId": {"$regex": search, "$options": "i"}},
        ]

    total = await db["vehicle_movement_logs"].count_documents(query)
    movements = await db["vehicle_movement_logs"].find(query).sort(
        "createdAt", -1
    ).skip(skip).limit(limit).to_list(limit)

    return {
        "total": total,
        "movements": [serialize_doc(m) for m in movements],
        "skip": skip,
        "limit": limit,
    }


async def return_vehicle(
    movement_id: str,
    dealer_id: str,
    staff_received_id: str,
    condition: str = None,
) -> dict:
    db = get_db()

    if ObjectId.is_valid(movement_id):
        query = {"_id": ObjectId(movement_id), "dealerId": dealer_id}
    else:
        query = {"movementId": movement_id, "dealerId": dealer_id}

    movement = await db["vehicle_movement_logs"].find_one(query)
    if not movement:
        raise HTTPException(status_code=404, detail="Movement log not found")

    if movement["status"] == "returned":
        raise HTTPException(status_code=400, detail="Vehicle already returned")

    await db["vehicle_movement_logs"].update_one(
        {"_id": movement["_id"]},
        {"$set": {
            "status": "returned",
            "timeReturned": datetime.utcnow(),
            "staffReceivedId": staff_received_id,
            "conditionOnReturn": condition,
            "updatedAt": datetime.utcnow(),
        }},
    )

    await db["car_listings"].update_one(
        {"carId": movement["carId"], "dealerId": dealer_id},
        {"$set": {"status": "available", "updatedAt": datetime.utcnow()}},
    )

    return {
        "message": "Vehicle returned successfully",
        "movementId": movement.get("movementId"),
        "timeReturned": datetime.utcnow().isoformat(),
    }


async def get_overdue_movements(dealer_id: str) -> list:
    db = get_db()

    now = datetime.utcnow()
    overdue = await db["vehicle_movement_logs"].find({
        "dealerId": dealer_id,
        "status": "out",
        "expectedReturnTime": {"$lt": now, "$ne": None},
    }).to_list(50)

    return [serialize_doc(m) for m in overdue]
