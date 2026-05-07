from fastapi import APIRouter, Depends, Query, Body
from typing import Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_dealer, get_current_user
from app.modules.dealers.service import get_dealer_by_user_id, serialize_doc
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime
import random, string


class MovementCreateRequest(BaseModel):
    carId: str
    takenByName: str
    takenByPhone: str
    takenByAddress: Optional[str] = None
    takenByIdType: Optional[str] = None
    takenByIdNumber: Optional[str] = None
    takenByIdImageUrl: Optional[str] = None
    purpose: Optional[str] = "test_drive"
    expectedReturnTime: Optional[str] = None
    permittedBy: Optional[str] = None
    notes: Optional[str] = None


class MovementReturnRequest(BaseModel):
    returnedToName: Optional[str] = None
    condition: Optional[str] = "good"
    notes: Optional[str] = None


router = APIRouter(prefix="/api/v1/movements", tags=["Movements"])


def gen_id():
    return "MOV-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


@router.post("/")
async def log_movement(
    data: MovementCreateRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    car = await db["car_listings"].find_one({
        "carId": data.carId, "dealerId": dealer["_id"]
    })
    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Car not found in your inventory")

    doc = {
        "movementId": gen_id(),
        "carId": data.carId,
        "carMongoId": str(car["_id"]),
        "carBrand": car.get("brand"),
        "carModel": car.get("model"),
        "carYear": car.get("year"),
        "dealerId": dealer["_id"],
        "loggedBy": str(current_user["_id"]),
        "takenByName": data.takenByName,
        "takenByPhone": data.takenByPhone,
        "takenByAddress": data.takenByAddress,
        "takenByIdType": data.takenByIdType,
        "takenByIdNumber": data.takenByIdNumber,
        "takenByIdImageUrl": data.takenByIdImageUrl,
        "purpose": data.purpose,
        "expectedReturnTime": data.expectedReturnTime,
        "permittedBy": data.permittedBy,
        "notes": data.notes,
        "status": "out",
        "timeOut": datetime.utcnow(),
        "timeReturned": None,
        "returnedToName": None,
        "returnCondition": None,
        "editHistory": [],
        "createdAt": datetime.utcnow(),
    }

    await db["car_listings"].update_one(
        {"_id": car["_id"]},
        {"$set": {"status": "out_for_inspection", "updatedAt": datetime.utcnow()}},
    )

    result = await db["vehicle_movement_logs"].insert_one(doc)
    doc["_id"] = result.inserted_id
    return serialize_doc(doc)


@router.get("/")
async def list_movements(
    status: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(30),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    query = {"dealerId": dealer["_id"]}
    if status:
        query["status"] = status

    total = await db["vehicle_movement_logs"].count_documents(query)
    movs = await db["vehicle_movement_logs"].find(query).sort(
        "createdAt", -1
    ).skip(skip).limit(limit).to_list(limit)

    return {"total": total, "movements": [serialize_doc(m) for m in movs]}


@router.patch("/{movement_id}/return")
async def return_vehicle(
    movement_id: str,
    data: MovementReturnRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    mov = await db["vehicle_movement_logs"].find_one({
        "movementId": movement_id, "dealerId": dealer["_id"]
    })
    if not mov:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Movement not found")

    now = datetime.utcnow()
    await db["vehicle_movement_logs"].update_one(
        {"movementId": movement_id},
        {"$set": {
            "status": "returned",
            "timeReturned": now,
            "returnedToName": data.returnedToName or str(current_user["_id"]),
            "returnCondition": data.condition,
            "returnNotes": data.notes,
            "updatedAt": now,
        }},
    )

    await db["car_listings"].update_one(
        {"carId": mov["carId"]},
        {"$set": {"status": "available", "updatedAt": now}},
    )

    updated = await db["vehicle_movement_logs"].find_one({"movementId": movement_id})
    return serialize_doc(updated)


@router.patch("/{movement_id}/edit")
async def edit_movement(
    movement_id: str,
    data: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    mov = await db["vehicle_movement_logs"].find_one({
        "movementId": movement_id, "dealerId": dealer["_id"]
    })
    if not mov:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Movement not found")

    edit_history = mov.get("editHistory", [])
    edit_history.append({
        "editedAt": datetime.utcnow().isoformat(),
        "editedBy": str(current_user["_id"]),
        "previous": {
            "takenByName": mov.get("takenByName"),
            "takenByPhone": mov.get("takenByPhone"),
            "purpose": mov.get("purpose"),
            "notes": mov.get("notes"),
        },
        "reason": data.get("editReason", ""),
    })

    allowed = [
        "takenByName","takenByPhone","takenByAddress",
        "takenByIdType","takenByIdNumber","takenByIdImageUrl",
        "purpose","expectedReturnTime","permittedBy","notes",
    ]
    update = {k: v for k, v in data.items() if k in allowed}
    update["editHistory"] = edit_history
    update["updatedAt"] = datetime.utcnow()

    await db["vehicle_movement_logs"].update_one(
        {"movementId": movement_id}, {"$set": update}
    )
    updated = await db["vehicle_movement_logs"].find_one({"movementId": movement_id})
    return serialize_doc(updated)
