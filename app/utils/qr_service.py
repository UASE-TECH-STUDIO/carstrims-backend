import qrcode
import qrcode.image.svg
from io import BytesIO
import cloudinary
import cloudinary.uploader
from datetime import datetime
from bson import ObjectId
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc
import base64


def generate_qr_base64(url: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    b64 = base64.b64encode(buffer.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


async def generate_dealer_qr(dealer_id: str, frontend_url: str = "http://localhost:3000") -> dict:
    db = get_db()

    if ObjectId.is_valid(dealer_id):
        query = {"_id": ObjectId(dealer_id)}
    else:
        query = {"dealerId": dealer_id}

    dealer = await db["dealer_organizations"].find_one(query)
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")

    dealer_page_url = f"{frontend_url}/dealers/{dealer.get('dealerId')}"
    qr_base64 = generate_qr_base64(dealer_page_url)

    try:
        buffer = BytesIO(base64.b64decode(qr_base64.split(",")[1]))
        result = cloudinary.uploader.upload(
            buffer.getvalue(),
            folder=f"car-dealer-app/dealers/{str(dealer['_id'])}/qr",
            public_id=f"qr-{dealer.get('dealerId')}",
            overwrite=True,
        )
        qr_url = result["secure_url"]
    except Exception:
        qr_url = qr_base64

    await db["dealer_organizations"].update_one(
        {"_id": dealer["_id"]},
        {"$set": {"qrCode": qr_url, "updatedAt": datetime.utcnow()}},
    )

    return {
        "qrCode": qr_url,
        "dealerUrl": dealer_page_url,
        "dealerId": dealer.get("dealerId"),
    }


async def get_dealer_qr(dealer_id: str) -> dict:
    db = get_db()

    if ObjectId.is_valid(dealer_id):
        query = {"_id": ObjectId(dealer_id)}
    else:
        query = {"dealerId": dealer_id}

    dealer = await db["dealer_organizations"].find_one(query)
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")

    if not dealer.get("qrCode"):
        return await generate_dealer_qr(dealer_id)

    return {
        "qrCode": dealer.get("qrCode"),
        "dealerUrl": f"http://localhost:3000/dealers/{dealer.get('dealerId')}",
        "dealerId": dealer.get("dealerId"),
    }
