"""
Sale recording service:
- mark_car_sold: changes car status to "sold", creates sale transaction
- generate_receipt: returns structured receipt data (PDF rendered on frontend)
- get_car_financial_report: full financial statement for a single car
"""
from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc
import random, string


def _gen_txn():
    return "TXN-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


async def mark_car_sold(dealer_id: str, user_id: str, car_id: str, sale_data: dict) -> dict:
    """
    Mark a car as sold and create the sale transaction.
    car_id can be carId string or MongoDB _id.
    sale_data must include: sellingPrice. Optional: buyerName, buyerPhone,
    buyerEmail, paymentMethod, notes, purchasePrice.
    """
    db = get_db()

    # Resolve car
    car = None
    if ObjectId.is_valid(car_id):
        car = await db["car_listings"].find_one({"_id": ObjectId(car_id)})
    if not car:
        car = await db["car_listings"].find_one({"carId": car_id})
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    # Ensure car belongs to this dealer
    if str(car.get("dealerId", "")) != str(dealer_id):
        raise HTTPException(status_code=403, detail="This car does not belong to your dealership")

    if car.get("status") == "sold":
        raise HTTPException(status_code=400, detail="Car is already marked as sold")

    selling_price = float(sale_data.get("sellingPrice", 0))
    purchase_price = float(sale_data.get("purchasePrice") or car.get("purchasePrice", 0) or 0)

    # Tally expenses for this car
    expense_result = await db["expense_records"].aggregate([
        {"$match": {"carId": car.get("carId"), "dealerId": dealer_id}},
        {"$group": {"_id": None, "total": {"$sum": "$amount"}}},
    ]).to_list(1)
    total_expenses = expense_result[0]["total"] if expense_result else 0

    profit = selling_price - purchase_price
    net_profit = profit - total_expenses

    txn_id = _gen_txn()
    now = datetime.utcnow()

    sale_doc = {
        "transactionId": txn_id,
        "carId": car.get("carId"),
        "carMongoId": car["_id"],
        "dealerId": dealer_id,
        "staffId": user_id,
        "carBrand": car.get("brand"),
        "carModel": car.get("model"),
        "carYear": car.get("year"),
        "carColor": car.get("color"),
        "vin": car.get("vin"),
        "sellingPrice": selling_price,
        "purchasePrice": purchase_price,
        "profit": profit,
        "expenses": total_expenses,
        "netProfit": net_profit,
        "buyerName": sale_data.get("buyerName"),
        "buyerPhone": sale_data.get("buyerPhone"),
        "buyerEmail": sale_data.get("buyerEmail"),
        "buyerAddress": sale_data.get("buyerAddress"),
        "paymentType": sale_data.get("paymentType", "full"),
        "installmentPlan": sale_data.get("installmentPlan"),
        "paymentMethod": sale_data.get("paymentMethod", "cash"),
        "notes": sale_data.get("notes"),
        "isManual": False,
        "editHistory": [],
        "soldAt": now,
        "createdAt": now,
    }

    await db["sale_transactions"].insert_one(sale_doc)

    # Update car status to sold
    await db["car_listings"].update_one(
        {"_id": car["_id"]},
        {"$set": {
            "status": "sold",
            "soldAt": now,
            "soldPrice": selling_price,
            "buyerName": sale_data.get("buyerName"),
            "updatedAt": now,
        }},
    )

    # Update dealer stats
    await db["dealer_organizations"].update_one(
        {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id},
        {"$inc": {"totalCarsSold": 1, "totalRevenue": selling_price}},
    )

    return {**serialize_doc(sale_doc), "car": serialize_doc(car)}


async def get_car_financial_report(dealer_id: str, car_id: str) -> dict:
    """Full financial statement for a single car."""
    db = get_db()

    car = None
    if ObjectId.is_valid(car_id):
        car = await db["car_listings"].find_one({"_id": ObjectId(car_id)})
    if not car:
        car = await db["car_listings"].find_one({"carId": car_id})
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    car_id_str = car.get("carId")

    # Expenses
    expenses = await db["expense_records"].find({"carId": car_id_str, "dealerId": dealer_id}).to_list(100)
    total_expenses = sum(e.get("amount", 0) for e in expenses)

    # Sale transaction
    sale = await db["sale_transactions"].find_one({"carId": car_id_str, "dealerId": dealer_id})

    # Movements
    movements = await db["car_movements"].find({"carId": car_id_str}).sort("createdAt", -1).to_list(50)

    # Dealer info
    dealer = await db["dealer_organizations"].find_one(
        {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
    )

    purchase_price = float(car.get("purchasePrice", 0) or 0)
    selling_price = float(sale.get("sellingPrice", 0) if sale else 0)
    profit = selling_price - purchase_price
    net_profit = profit - total_expenses

    return {
        "car": serialize_doc(car),
        "dealer": serialize_doc(dealer) if dealer else {},
        "financials": {
            "purchasePrice": purchase_price,
            "sellingPrice": selling_price,
            "totalExpenses": total_expenses,
            "grossProfit": profit,
            "netProfit": net_profit,
            "margin": round((profit / selling_price * 100), 2) if selling_price else 0,
        },
        "expenses": [serialize_doc(e) for e in expenses],
        "sale": serialize_doc(sale) if sale else None,
        "movements": [serialize_doc(m) for m in movements],
        "generatedAt": datetime.utcnow().isoformat(),
    }


async def generate_receipt_data(dealer_id: str, transaction_id: str) -> dict:
    """Returns all data needed to render a receipt/invoice PDF on the frontend."""
    db = get_db()

    sale = await db["sale_transactions"].find_one({"transactionId": transaction_id, "dealerId": dealer_id})
    if not sale:
        raise HTTPException(status_code=404, detail="Transaction not found")

    dealer = await db["dealer_organizations"].find_one(
        {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
    )

    car = None
    if sale.get("carMongoId"):
        car = await db["car_listings"].find_one({"_id": sale["carMongoId"]})
    if not car and sale.get("carId"):
        car = await db["car_listings"].find_one({"carId": sale["carId"]})

    return {
        "receiptNumber": sale["transactionId"],
        "issuedAt": sale.get("soldAt") or sale.get("createdAt"),
        "dealer": {
            "name": dealer.get("companyName") if dealer else "CARSTRIMS Dealer",
            "logo": dealer.get("logo") if dealer else None,
            "phone": dealer.get("phone") if dealer else None,
            "whatsapp": dealer.get("whatsapp") if dealer else None,
            "email": dealer.get("email") if dealer else None,
            "address": dealer.get("address") if dealer else None,
            "city": dealer.get("city") if dealer else None,
            "state": dealer.get("state") if dealer else None,
        },
        "car": {
            "brand": sale.get("carBrand") or (car.get("brand") if car else ""),
            "model": sale.get("carModel") or (car.get("model") if car else ""),
            "year": sale.get("carYear") or (car.get("year") if car else ""),
            "color": sale.get("carColor") or (car.get("color") if car else ""),
            "vin": sale.get("vin") or (car.get("vin") if car else ""),
            "carId": sale.get("carId"),
            "image": car.get("images", [None])[0] if car and car.get("images") else None,
        },
        "buyer": {
            "name": sale.get("buyerName"),
            "phone": sale.get("buyerPhone"),
            "email": sale.get("buyerEmail"),
            "address": sale.get("buyerAddress"),
            "paymentType": sale.get("paymentType", "full"),
            "installmentPlan": sale.get("installmentPlan"),
        },
        "financials": {
            "sellingPrice": sale.get("sellingPrice", 0),
            "paymentMethod": sale.get("paymentMethod", "cash"),
            "notes": sale.get("notes"),
        },
        "platform": {
            "name": "CARSTRIMS",
            "poweredBy": "UASE TECH STUDIO",
        },
    }