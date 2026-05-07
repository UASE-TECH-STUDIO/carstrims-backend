from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc
import random
import string


def generate_expense_id():
    return "EXP-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


async def create_expense(dealer_id: str, user_id: str, data: dict) -> dict:
    db = get_db()

    car_id = data.get("carId")
    if car_id:
        car = await db["car_listings"].find_one({"carId": car_id, "dealerId": dealer_id})
        if not car:
            raise HTTPException(status_code=404, detail="Car not found in your inventory")

    expense_doc = {
        "expenseId": generate_expense_id(),
        "dealerId": dealer_id,
        "recordedById": user_id,
        "carId": car_id,
        "category": data.get("category", "miscellaneous"),
        "amount": float(data.get("amount", 0)),
        "description": data.get("description"),
        "receiptUrl": data.get("receiptUrl"),
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    result = await db["expense_records"].insert_one(expense_doc)
    expense_doc["_id"] = result.inserted_id
    return serialize_doc(expense_doc)


async def get_dealer_expenses(
    dealer_id: str,
    car_id: str = None,
    category: str = None,
    skip: int = 0,
    limit: int = 30,
) -> dict:
    db = get_db()

    query = {"dealerId": dealer_id}
    if car_id:
        query["carId"] = car_id
    if category:
        query["category"] = category

    total = await db["expense_records"].count_documents(query)
    expenses = await db["expense_records"].find(query).sort(
        "createdAt", -1
    ).skip(skip).limit(limit).to_list(limit)

    total_amount_result = await db["expense_records"].aggregate([
        {"$match": query},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_amount = total_amount_result[0]["total"] if total_amount_result else 0

    by_category = await db["expense_records"].aggregate([
        {"$match": {"dealerId": dealer_id}},
        {"$group": {"_id": "$category", "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}},
    ]).to_list(20)

    return {
        "total": total,
        "totalAmount": total_amount,
        "expenses": [serialize_doc(e) for e in expenses],
        "byCategory": [{"category": b["_id"], "total": b["total"], "count": b["count"]} for b in by_category],
        "skip": skip,
        "limit": limit,
    }


async def get_car_expenses(car_id: str, dealer_id: str) -> dict:
    db = get_db()

    expenses = await db["expense_records"].find(
        {"carId": car_id, "dealerId": dealer_id}
    ).sort("createdAt", -1).to_list(100)

    total_result = await db["expense_records"].aggregate([
        {"$match": {"carId": car_id, "dealerId": dealer_id}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    total = total_result[0]["total"] if total_result else 0

    return {
        "expenses": [serialize_doc(e) for e in expenses],
        "totalExpenses": total,
    }


async def delete_expense(expense_id: str, dealer_id: str) -> dict:
    db = get_db()

    if ObjectId.is_valid(expense_id):
        query = {"_id": ObjectId(expense_id), "dealerId": dealer_id}
    else:
        query = {"expenseId": expense_id, "dealerId": dealer_id}

    expense = await db["expense_records"].find_one(query)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    await db["expense_records"].delete_one({"_id": expense["_id"]})
    return {"message": "Expense deleted"}


async def get_sales_log(
    dealer_id: str,
    skip: int = 0,
    limit: int = 30,
    search: str = None,
) -> dict:
    db = get_db()

    query = {"dealerId": dealer_id}
    if search:
        query["$or"] = [
            {"transactionId": {"$regex": search, "$options": "i"}},
            {"carId": {"$regex": search, "$options": "i"}},
            {"buyerName": {"$regex": search, "$options": "i"}},
        ]

    total = await db["sale_transactions"].count_documents(query)
    sales = await db["sale_transactions"].find(query).sort(
        "soldAt", -1
    ).skip(skip).limit(limit).to_list(limit)

    summary = await db["sale_transactions"].aggregate([
        {"$match": {"dealerId": dealer_id}},
        {"$group": {
            "_id": None,
            "totalRevenue": {"$sum": "$sellingPrice"},
            "totalProfit": {"$sum": "$profit"},
            "totalNetProfit": {"$sum": "$netProfit"},
            "totalSales": {"$sum": 1},
        }},
    ]).to_list(1)

    return {
        "total": total,
        "summary": summary[0] if summary else {
            "totalRevenue": 0, "totalProfit": 0,
            "totalNetProfit": 0, "totalSales": 0,
        },
        "sales": [serialize_doc(s) for s in sales],
        "skip": skip,
        "limit": limit,
    }
