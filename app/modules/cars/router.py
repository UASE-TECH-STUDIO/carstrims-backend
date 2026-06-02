from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from typing import Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_user, get_current_dealer, get_current_dealer_or_staff
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
async def add_car(data: dict, current_user: dict = Depends(get_current_dealer_or_staff)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await create_car(dealer["_id"], str(current_user["_id"]), data)


@router.get("/")
async def list_cars(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(20),
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await get_dealer_cars(dealer["_id"], status, search, skip, limit)


@router.get("/{car_id}")
async def get_car(car_id: str, current_user: dict = Depends(get_current_dealer_or_staff)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await get_car_by_id(car_id, dealer["_id"])


@router.patch("/{car_id}")
async def update_car_details(
    car_id: str,
    data: dict,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
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
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await mark_car_sold(car_id, dealer["_id"], str(current_user["_id"]), data)


@router.delete("/{car_id}")
async def remove_car(
    car_id: str,
    reason: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
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



#  MARK CAR AS SOLD (from inventory or car detail) 
from pydantic import BaseModel as _PBM
from typing import Optional as _Opt

class SaleEntryRequest(_PBM):
    sellingPrice: float
    purchasePrice: _Opt[float] = None
    buyerName: _Opt[str] = None
    buyerPhone: _Opt[str] = None
    buyerEmail: _Opt[str] = None
    paymentMethod: _Opt[str] = "cash"
    notes: _Opt[str] = None

@router.post("/{car_id}/mark-sold")
async def mark_car_sold_endpoint(
    car_id: str,
    data: SaleEntryRequest,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    from app.modules.dealers.service import get_dealer_by_user_id
    from app.modules.cars.sale_service import mark_car_sold
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await mark_car_sold(dealer["_id"], str(current_user["_id"]), car_id, data.model_dump())

@router.get("/{car_id}/financial-report")
async def car_financial_report(
    car_id: str,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    from app.modules.dealers.service import get_dealer_by_user_id
    from app.modules.cars.sale_service import get_car_financial_report
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await get_car_financial_report(dealer["_id"], car_id)


#  DOCUMENT GENERATION ENDPOINTS 

@router.get("/{car_id}/proforma-invoice")
async def get_proforma_invoice(
    car_id: str,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    """Proforma Invoice: formal quote BEFORE sale is confirmed."""
    from app.modules.cars.documents_service import generate_proforma_invoice
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await generate_proforma_invoice(str(dealer["_id"]), car_id)


@router.get("/{car_id}/invoice")
async def get_standard_invoice(
    car_id: str,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    """Standard Invoice: official bill AFTER car is confirmed/delivered."""
    from app.modules.cars.documents_service import generate_standard_invoice
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await generate_standard_invoice(str(dealer["_id"]), car_id)


@router.get("/{car_id}/receipt")
async def get_receipt(
    car_id: str,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    """Receipt: proof of payment AFTER money has been received."""
    from app.modules.cars.documents_service import generate_receipt
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await generate_receipt(str(dealer["_id"]), car_id)


@router.get("/{car_id}/report")
async def get_car_report(
    car_id: str,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    """Full car financial report: purchase price, expenses, sale, profit/loss."""
    from app.modules.cars.sale_service import get_car_financial_report
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await get_car_financial_report(str(dealer["_id"]), car_id)
