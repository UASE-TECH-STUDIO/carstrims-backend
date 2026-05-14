from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from typing import Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_user, get_current_dealer
from app.modules.cars.service import (
    create_car, get_dealer_cars, update_car, mark_car_sold,
    delete_car, get_public_cars, get_car_by_id,
)
from app.modules.dealers.service import get_dealer_by_user_id, serialize_doc
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime

router = APIRouter(prefix="/api/v1/cars", tags=["Cars"])


@router.post("/")
async def add_car(data: dict, current_user: dict = Depends(get_current_dealer)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await create_car(dealer["_id"], str(current_user["_id"]), data)


@router.get("/")
async def list_cars(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(20),
    current_user: dict = Depends(get_current_dealer),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await get_dealer_cars(dealer["_id"], status, search, skip, limit)


@router.get("/{car_id}")
async def get_car(car_id: str, current_user: dict = Depends(get_current_dealer)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await get_car_by_id(car_id, dealer["_id"])


@router.patch("/{car_id}")
async def update_car_details(
    car_id: str,
    data: dict,
    current_user: dict = Depends(get_current_dealer),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    db = get_db()

    if ObjectId.is_valid(car_id):
        query = {"_id": ObjectId(car_id), "dealerId": dealer["_id"]}
    else:
        query = {"carId": car_id, "dealerId": dealer["_id"]}

    car = await db["car_listings"].find_one(query)
    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Car not found")

    protected = ["_id", "carId", "dealerId", "createdAt"]
    update = {k: v for k, v in data.items() if k not in protected}
    update["updatedAt"] = datetime.utcnow()

    await db["car_listings"].update_one({"_id": car["_id"]}, {"$set": update})
    updated = await db["car_listings"].find_one({"_id": car["_id"]})
    return serialize_doc(updated)


@router.post("/{car_id}/sold")
async def sell_car(
    car_id: str,
    data: dict,
    current_user: dict = Depends(get_current_dealer),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await mark_car_sold(car_id, dealer["_id"], str(current_user["_id"]), data)


@router.delete("/{car_id}")
async def remove_car(
    car_id: str,
    reason: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_dealer),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    db = get_db()

    if ObjectId.is_valid(car_id):
        query = {"_id": ObjectId(car_id), "dealerId": dealer["_id"]}
    else:
        query = {"carId": car_id, "dealerId": dealer["_id"]}

    car = await db["car_listings"].find_one(query)
    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Car not found")

    await db["deletion_logs"].insert_one({
        "type": "car",
        "itemId": car.get("carId"),
        "itemData": serialize_doc(car),
        "reason": reason or "No reason provided",
        "deletedBy": str(current_user["_id"]),
        "dealerId": dealer["_id"],
        "deletedAt": datetime.utcnow(),
    })

    await db["car_listings"].delete_one({"_id": car["_id"]})
    return {"message": "Car deleted", "carId": car.get("carId")}

