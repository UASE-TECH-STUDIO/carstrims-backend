from fastapi import APIRouter, Depends, Query, Body
from typing import Optional
from app.auth.dependencies import get_current_user, get_current_dealer
from app.modules.dealers.service import get_dealer_by_user_id, serialize_doc
from app.utils.qr_service import generate_dealer_qr, get_dealer_qr
from app.utils.comments_service import add_comment, get_car_comments, delete_comment, add_reply
from app.modules.users.user_service import toggle_like, get_user_likes, add_favorite, remove_favorite
from app.modules.cars.service import get_public_cars, get_car_by_id
from app.database.connection import get_db
from bson import ObjectId
from pydantic import BaseModel
from app.config.settings import settings


class CommentBody(BaseModel):
    text: str


class ReplyBody(BaseModel):
    text: str


router = APIRouter(prefix="/api/v1/public", tags=["Public Feed"])


# ── PUBLIC CAR FEED ───────────────────────────────────────────

@router.get("/cars")
async def public_car_feed(
    search: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    city: Optional[str] = Query(None),
    sort: Optional[str] = Query("newest"),
    skip: int = Query(0),
    limit: int = Query(20),
):
    return await get_public_cars(search, brand, min_price, max_price, city, skip, limit)


@router.get("/cars/{car_id}")
async def public_car_detail(car_id: str):
    db = get_db()
    if ObjectId.is_valid(car_id):
        car = await db["car_listings"].find_one({"_id": ObjectId(car_id), "status": {"$ne": "draft"}})
    else:
        car = await db["car_listings"].find_one({"carId": car_id, "status": {"$ne": "draft"}})

    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Car not found")

    # increment view count
    await db["car_listings"].update_one({"_id": car["_id"]}, {"$inc": {"viewCount": 1}})

    serialized = serialize_doc(car)

    dealer = await db["dealer_organizations"].find_one(
        {"_id": ObjectId(car["dealerId"])}
    ) if ObjectId.is_valid(car.get("dealerId", "")) else None

    if dealer:
        serialized["dealer"] = {
            "dealerId": dealer.get("dealerId"),
            "companyName": dealer.get("companyName"),
            "ownerName": dealer.get("ownerName"),
            "logo": dealer.get("logo"),
            "phone": dealer.get("phone"),
            "whatsapp": dealer.get("whatsapp"),
            "email": dealer.get("email"),
            "city": dealer.get("city"),
            "state": dealer.get("state"),
            "qrCode": dealer.get("qrCode"),
        }

    return serialized


@router.get("/dealers")
async def public_dealers(
    search: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(20),
):
    db = get_db()
    query = {"status": "approved"}
    if search:
        query["$or"] = [
            {"companyName": {"$regex": search, "$options": "i"}},
            {"ownerName": {"$regex": search, "$options": "i"}},
        ]
    if city:
        query["city"] = {"$regex": city, "$options": "i"}

    total = await db["dealer_organizations"].count_documents(query)
    dealers = await db["dealer_organizations"].find(query).sort(
        "totalCarsSold", -1
    ).skip(skip).limit(limit).to_list(limit)

    return {
        "total": total,
        "dealers": [serialize_doc(d) for d in dealers],
    }


@router.get("/dealers/{dealer_id}")
async def public_dealer_profile(dealer_id: str):
    db = get_db()
    if ObjectId.is_valid(dealer_id):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    else:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})

    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")

    cars = await db["car_listings"].find(
        {"dealerId": str(dealer["_id"]), "status": "available"}
    ).sort("createdAt", -1).limit(20).to_list(20)

    result = serialize_doc(dealer)
    result["availableCars"] = [serialize_doc(c) for c in cars]
    return result


# ── QR CODE ───────────────────────────────────────────────────

@router.post("/qr/generate")
async def generate_qr(current_user: dict = Depends(get_current_dealer)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    frontend_url = settings.FRONTEND_URL
    return await generate_dealer_qr(dealer["_id"], frontend_url)


@router.get("/qr/me")
async def get_my_qr(current_user: dict = Depends(get_current_dealer)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await get_dealer_qr(dealer["_id"])


@router.get("/qr/{dealer_id}")
async def get_dealer_qr_public(dealer_id: str):
    return await get_dealer_qr(dealer_id)


# ── LIKES ────────────────────────────────────────────────────

@router.post("/cars/{car_id}/like")
async def like_car(car_id: str, current_user: dict = Depends(get_current_user)):
    return await toggle_like(str(current_user["_id"]), car_id)


@router.post("/cars/{car_id}/favorite")
async def favorite_car(car_id: str, current_user: dict = Depends(get_current_user)):
    return await add_favorite(str(current_user["_id"]), car_id)


@router.delete("/cars/{car_id}/favorite")
async def unfavorite_car(car_id: str, current_user: dict = Depends(get_current_user)):
    return await remove_favorite(str(current_user["_id"]), car_id)


@router.get("/cars/{car_id}/likes/me")
async def my_like_status(car_id: str, current_user: dict = Depends(get_current_user)):
    from app.database.connection import get_db
    db = get_db()
    liked = await db["car_likes"].find_one({"userId": str(current_user["_id"]), "carId": car_id})
    faved = await db["favorites"].find_one({"userId": str(current_user["_id"]), "carId": car_id})
    return {"liked": bool(liked), "favorited": bool(faved)}


# ── COMMENTS ────────────────────────────────────────────────

@router.post("/cars/{car_id}/comments")
async def post_comment(
    car_id: str,
    body: CommentBody,
    current_user: dict = Depends(get_current_user),
):
    return await add_comment(str(current_user["_id"]), car_id, body.text)


@router.get("/cars/{car_id}/comments")
async def list_comments(
    car_id: str,
    skip: int = Query(0),
    limit: int = Query(20),
):
    return await get_car_comments(car_id, skip, limit)


@router.delete("/cars/{car_id}/comments/{comment_id}")
async def remove_comment(
    car_id: str,
    comment_id: str,
    current_user: dict = Depends(get_current_user),
):
    return await delete_comment(comment_id, str(current_user["_id"]))


@router.post("/cars/{car_id}/comments/{comment_id}/reply")
async def reply_comment(
    car_id: str,
    comment_id: str,
    body: ReplyBody,
    current_user: dict = Depends(get_current_user),
):
    return await add_reply(str(current_user["_id"]), comment_id, body.text)
