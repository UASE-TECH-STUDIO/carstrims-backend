from fastapi import APIRouter, Depends, Query, Body
from typing import Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_dealer
from app.modules.inventory.service import (
    create_expense, get_dealer_expenses, get_car_expenses,
    delete_expense, get_sales_log,
)
from app.modules.dealers.service import get_dealer_by_user_id
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc
from bson import ObjectId
from datetime import datetime
import random, string


class ExpenseCreateRequest(BaseModel):
    carId: Optional[str] = None
    category: str
    amount: float
    description: Optional[str] = None
    receiptUrl: Optional[str] = None


class ManualSaleRequest(BaseModel):
    carId: Optional[str] = None
    carBrand: str
    carModel: str
    carYear: Optional[int] = None
    sellingPrice: float
    purchasePrice: Optional[float] = 0
    buyerName: Optional[str] = None
    buyerPhone: Optional[str] = None
    paymentMethod: Optional[str] = "cash"
    notes: Optional[str] = None


class SaleUpdateRequest(BaseModel):
    sellingPrice: Optional[float] = None
    buyerName: Optional[str] = None
    buyerPhone: Optional[str] = None
    paymentMethod: Optional[str] = None
    notes: Optional[str] = None
    editReason: Optional[str] = None


router = APIRouter(prefix="/api/v1/inventory", tags=["Inventory"])


@router.post("/expenses")
async def add_expense(data: ExpenseCreateRequest, current_user: dict = Depends(get_current_dealer)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await create_expense(dealer["_id"], str(current_user["_id"]), data.model_dump())


@router.get("/expenses")
async def list_expenses(
    car_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(30),
    current_user: dict = Depends(get_current_dealer),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await get_dealer_expenses(dealer["_id"], car_id, category, skip, limit)


@router.get("/expenses/car/{car_id}")
async def car_expenses(car_id: str, current_user: dict = Depends(get_current_dealer)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await get_car_expenses(car_id, dealer["_id"])


@router.patch("/expenses/{expense_id}")
async def edit_expense(
    expense_id: str,
    data: dict = Body(...),
    current_user: dict = Depends(get_current_dealer),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    if ObjectId.is_valid(expense_id):
        query = {"_id": ObjectId(expense_id), "dealerId": dealer["_id"]}
    else:
        query = {"expenseId": expense_id, "dealerId": dealer["_id"]}

    expense = await db["expense_records"].find_one(query)
    if not expense:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Expense not found")

    edit_history = expense.get("editHistory", [])
    edit_history.append({
        "editedAt": datetime.utcnow().isoformat(),
        "editedBy": str(current_user["_id"]),
        "previous": {
            "amount": expense.get("amount"),
            "category": expense.get("category"),
            "description": expense.get("description"),
        },
        "reason": data.get("editReason", "No reason given"),
    })

    allowed = ["amount", "category", "description"]
    update = {k: v for k, v in data.items() if k in allowed}
    update["editHistory"] = edit_history
    update["updatedAt"] = datetime.utcnow()

    await db["expense_records"].update_one({"_id": expense["_id"]}, {"$set": update})
    updated = await db["expense_records"].find_one({"_id": expense["_id"]})
    return serialize_doc(updated)


@router.delete("/expenses/{expense_id}")
async def remove_expense(expense_id: str, current_user: dict = Depends(get_current_dealer)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await delete_expense(expense_id, dealer["_id"])


@router.get("/sales")
async def list_sales(
    skip: int = Query(0),
    limit: int = Query(30),
    search: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_dealer),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await get_sales_log(dealer["_id"], skip, limit, search)


@router.post("/sales/manual")
async def add_manual_sale(
    data: ManualSaleRequest,
    current_user: dict = Depends(get_current_dealer),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    profit = data.sellingPrice - (data.purchasePrice or 0)
    trans_id = "TXN-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))

    sale_doc = {
        "transactionId": trans_id,
        "carId": data.carId or "MANUAL",
        "carMongoId": None,
        "dealerId": dealer["_id"],
        "staffId": str(current_user["_id"]),
        "carBrand": data.carBrand,
        "carModel": data.carModel,
        "carYear": data.carYear,
        "sellingPrice": data.sellingPrice,
        "purchasePrice": data.purchasePrice or 0,
        "profit": profit,
        "expenses": 0,
        "netProfit": profit,
        "paymentMethod": data.paymentMethod or "cash",
        "buyerName": data.buyerName,
        "buyerPhone": data.buyerPhone,
        "notes": data.notes,
        "isManual": True,
        "editHistory": [],
        "soldAt": datetime.utcnow(),
        "createdAt": datetime.utcnow(),
    }

    await db["sale_transactions"].insert_one(sale_doc)
    await db["dealer_organizations"].update_one(
        {"_id": ObjectId(dealer["_id"])},
        {"$inc": {"totalCarsSold": 1, "totalRevenue": data.sellingPrice}},
    )

    return serialize_doc(sale_doc)


@router.patch("/sales/{transaction_id}")
async def edit_sale(
    transaction_id: str,
    data: SaleUpdateRequest,
    current_user: dict = Depends(get_current_dealer),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    sale = await db["sale_transactions"].find_one({
        "transactionId": transaction_id,
        "dealerId": dealer["_id"],
    })
    if not sale:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Sale not found")

    edit_history = sale.get("editHistory", [])
    edit_history.append({
        "editedAt": datetime.utcnow().isoformat(),
        "editedBy": str(current_user["_id"]),
        "previous": {
            "sellingPrice": sale.get("sellingPrice"),
            "buyerName": sale.get("buyerName"),
            "paymentMethod": sale.get("paymentMethod"),
            "notes": sale.get("notes"),
        },
        "reason": data.editReason or "No reason given",
    })

    update_data = data.model_dump(exclude_none=True)
    update_data.pop("editReason", None)
    update_data["editHistory"] = edit_history
    update_data["isEdited"] = True
    update_data["updatedAt"] = datetime.utcnow()

    if "sellingPrice" in update_data:
        update_data["profit"] = update_data["sellingPrice"] - sale.get("purchasePrice", 0)

    await db["sale_transactions"].update_one(
        {"transactionId": transaction_id}, {"$set": update_data}
    )

    updated = await db["sale_transactions"].find_one({"transactionId": transaction_id})
    return serialize_doc(updated)


@router.post("/sales/{transaction_id}/revert")
async def revert_sale(
    transaction_id: str,
    current_user: dict = Depends(get_current_dealer),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    sale = await db["sale_transactions"].find_one({
        "transactionId": transaction_id,
        "dealerId": dealer["_id"],
    })
    if not sale:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Sale not found")

    history = sale.get("editHistory", [])
    if not history:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="No edit history to revert")

    last_edit = history[-1]
    previous = last_edit.get("previous", {})

    await db["sale_transactions"].update_one(
        {"transactionId": transaction_id},
        {"$set": {
            **previous,
            "isEdited": len(history) > 1,
            "editHistory": history[:-1],
            "updatedAt": datetime.utcnow(),
        }},
    )
    return {"message": "Sale reverted to previous values"}


# ── RECEIPT for a completed sale (called by InvoiceGenerator on Sales page) ───
@router.get("/sales/{transaction_id}/receipt")
async def get_sale_receipt(
    transaction_id: str,
    current_user: dict = Depends(get_current_dealer),
):
    """Return structured receipt/invoice data for a sale transaction."""
    from app.modules.cars.sale_service import generate_receipt_data
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await generate_receipt_data(str(dealer["_id"]), transaction_id)
