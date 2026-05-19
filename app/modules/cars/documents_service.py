"""
Document generation service.
Returns structured data for frontend to render as PDF/CSV/Print:
  - Proforma Invoice  (BEFORE sale — quote/estimate, not a bill)
  - Standard Invoice  (AFTER confirmation — official legally binding bill)
  - Receipt           (AFTER payment — proof money changed hands)
"""
from datetime import datetime, timedelta
from bson import ObjectId
from fastapi import HTTPException
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc
import random, string


def _doc_number(prefix: str) -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m')}-{suffix}"


async def _get_dealer_and_car(dealer_id: str, car_id: str):
    db = get_db()
    car = None
    if ObjectId.is_valid(car_id):
        car = await db["car_listings"].find_one({"_id": ObjectId(car_id)})
    if not car:
        car = await db["car_listings"].find_one({"carId": car_id})
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    dealer = None
    if ObjectId.is_valid(dealer_id):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    if not dealer:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})

    return car, dealer


def _dealer_block(dealer: dict) -> dict:
    if not dealer:
        return {}
    return {
        "companyName": dealer.get("companyName", "CARSTRIMS Dealer"),
        "logo": dealer.get("logo"),
        "signature": dealer.get("signature"),
        "phone": dealer.get("phone"),
        "whatsapp": dealer.get("whatsapp"),
        "email": dealer.get("email"),
        "address": dealer.get("address"),
        "city": dealer.get("city"),
        "state": dealer.get("state"),
        "country": dealer.get("country", "Nigeria"),
        "dealerId": dealer.get("dealerId"),
        "cacNumber": dealer.get("cacNumber"),
        "website": dealer.get("website"),
    }


def _car_block(car: dict) -> dict:
    return {
        "carId": car.get("carId"),
        "brand": car.get("brand"),
        "model": car.get("model"),
        "year": car.get("year"),
        "color": car.get("color"),
        "vin": car.get("vin"),
        "transmission": car.get("transmission"),
        "fuelType": car.get("fuelType"),
        "mileage": car.get("mileage"),
        "condition": car.get("condition"),
        "engineType": car.get("engineType"),
        "image": car.get("images", [None])[0] if car.get("images") else None,
    }


async def generate_proforma_invoice(dealer_id: str, car_id: str) -> dict:
    """
    PROFORMA INVOICE — issued BEFORE the sale is confirmed.
    It is a quote/estimate, NOT a demand for payment.
    Valid for 7 days from issuance.
    """
    car, dealer = await _get_dealer_and_car(dealer_id, car_id)

    selling_price = float(car.get("sellingPrice", 0))
    promo_price = float(car.get("promoPrice", 0) or 0)
    quoted_price = promo_price if promo_price and promo_price < selling_price else selling_price

    now = datetime.utcnow()
    valid_until = now + timedelta(days=7)

    return {
        "documentType": "PROFORMA_INVOICE",
        "documentNumber": _doc_number("PI"),
        "title": "Proforma Invoice",
        "subtitle": "Formal Quote - Not a Demand for Payment",
        "issuedAt": now.isoformat(),
        "validUntil": valid_until.isoformat(),
        "status": "QUOTE",
        "dealer": _dealer_block(dealer),
        "car": _car_block(car),
        "lineItems": [
            {
                "description": f"{car.get('brand')} {car.get('model')} {car.get('year')} - {car.get('color', '')}",
                "quantity": 1,
                "unitPrice": quoted_price,
                "total": quoted_price,
            },
        ],
        "financials": {
            "subtotal": quoted_price,
            "discount": max(0, selling_price - quoted_price),
            "total": quoted_price,
            "currency": "NGN",
        },
        "notes": (
            f"This proforma invoice is a formal quotation only. "
            f"It is NOT a request for payment and does NOT constitute a binding contract. "
            f"Valid for 7 days until {valid_until.strftime('%d %B %Y')}. "
            f"A standard invoice will be issued upon order confirmation."
        ),
        "footer": "Powered by CARSTRIMS - Built by UASE TECH STUDIO",
    }


async def generate_standard_invoice(dealer_id: str, car_id: str) -> dict:
    """
    STANDARD INVOICE — issued AFTER the car is confirmed/delivered.
    Official legally binding demand for payment.
    Includes VAT, payment due date. Goes into accounting books.
    """
    car, dealer = await _get_dealer_and_car(dealer_id, car_id)
    db = get_db()

    sale = await db["sale_transactions"].find_one({
        "carId": car.get("carId"), "dealerId": dealer_id
    })

    selling_price = float(sale.get("sellingPrice") if sale else car.get("sellingPrice", 0))
    buyer_name  = sale.get("buyerName")  if sale else None
    buyer_phone = sale.get("buyerPhone") if sale else None
    buyer_email = sale.get("buyerEmail") if sale else None

    now = datetime.utcnow()
    due_date = now + timedelta(days=30)

    vat_rate = 0.075
    vat_amount = round(selling_price * vat_rate, 2)
    total_with_vat = round(selling_price + vat_amount, 2)

    txn_id = sale.get("transactionId") if sale else _doc_number("INV")

    return {
        "documentType": "STANDARD_INVOICE",
        "documentNumber": txn_id,
        "title": "Invoice",
        "subtitle": "Official Bill - Legally Binding Demand for Payment",
        "issuedAt": now.isoformat(),
        "dueDate": due_date.isoformat(),
        "status": "INVOICE",
        "dealer": _dealer_block(dealer),
        "buyer": {
            "name": buyer_name,
            "phone": buyer_phone,
            "email": buyer_email,
        },
        "car": _car_block(car),
        "lineItems": [
            {
                "description": f"{car.get('brand')} {car.get('model')} {car.get('year')} - {car.get('color', '')}",
                "quantity": 1,
                "unitPrice": selling_price,
                "total": selling_price,
            },
            {
                "description": "VAT (7.5%)",
                "quantity": 1,
                "unitPrice": vat_amount,
                "total": vat_amount,
            },
        ],
        "financials": {
            "subtotal": selling_price,
            "vatRate": vat_rate,
            "vatAmount": vat_amount,
            "total": total_with_vat,
            "currency": "NGN",
            "paymentMethod": sale.get("paymentMethod", "TBD") if sale else "TBD",
        },
        "paymentInstructions": (
            f"Payment is due by {due_date.strftime('%d %B %Y')}. "
            "Bank transfer, cash, or card accepted. "
            "Quote this invoice number in all correspondence."
        ),
        "notes": sale.get("notes") if sale else None,
        "legalNote": (
            "This is an official tax invoice. It is a legally binding document "
            "and has been entered into the issuer's accounting records."
        ),
        "footer": "Powered by CARSTRIMS - Built by UASE TECH STUDIO",
    }


async def generate_receipt(dealer_id: str, car_id: str) -> dict:
    """
    RECEIPT — issued AFTER full payment has been received.
    Proof that money changed hands. Debt from invoice is now settled.
    """
    db = get_db()
    car, dealer = await _get_dealer_and_car(dealer_id, car_id)

    sale = await db["sale_transactions"].find_one({
        "carId": car.get("carId"), "dealerId": dealer_id
    })
    if not sale:
        raise HTTPException(
            status_code=400,
            detail="No sale recorded for this car yet. Record a sale first, then generate a receipt."
        )

    selling_price = float(sale.get("sellingPrice", 0))
    now = datetime.utcnow()
    sold_at = sale.get("soldAt")
    sold_at_str = sold_at.isoformat() if sold_at else now.isoformat()

    return {
        "documentType": "RECEIPT",
        "documentNumber": f"RCP-{sale.get('transactionId', _doc_number('RCP'))}",
        "title": "Payment Receipt",
        "subtitle": "Proof of Payment - Transaction Complete",
        "issuedAt": now.isoformat(),
        "soldAt": sold_at_str,
        "status": "PAID",
        "dealer": _dealer_block(dealer),
        "buyer": {
            "name": sale.get("buyerName"),
            "phone": sale.get("buyerPhone"),
            "email": sale.get("buyerEmail"),
        },
        "car": _car_block(car),
        "transaction": {
            "transactionId": sale.get("transactionId"),
            "paymentMethod": sale.get("paymentMethod", "cash"),
            "amountPaid": selling_price,
            "currency": "NGN",
            "notes": sale.get("notes"),
        },
        "financials": {
            "amountPaid": selling_price,
            "currency": "NGN",
            "balanceDue": 0,
        },
        "confirmation": (
            f"This is to confirm that payment of {selling_price:,.0f} NGN has been received "
            f"in full for the vehicle described above. "
            f"The transaction is now complete. Thank you for your business."
        ),
        "footer": "Powered by CARSTRIMS - Built by UASE TECH STUDIO",
    }
