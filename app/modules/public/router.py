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
from datetime import datetime


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
    condition: Optional[str] = Query(None),
    transmission: Optional[str] = Query(None),
    fuel_type: Optional[str] = Query(None),
    status: Optional[str] = Query("available"),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    city: Optional[str] = Query(None),
    year_from: Optional[int] = Query(None),
    year_to: Optional[int] = Query(None),
    color: Optional[str] = Query(None),
    sort: Optional[str] = Query("newest"),
    skip: int = Query(0),
    limit: int = Query(20),
):
    db = get_db()
    query: dict = {}

    if status and status != "all":
        query["status"] = status

    if search:
        query["$or"] = [
            {"brand": {"$regex": search, "$options": "i"}},
            {"model": {"$regex": search, "$options": "i"}},
            {"year": {"$regex": str(search), "$options": "i"}} if str(search).isdigit() else {},
            {"color": {"$regex": search, "$options": "i"}},
            {"carId": {"$regex": search, "$options": "i"}},
        ]
        # Remove empty dict from $or
        query["$or"] = [q for q in query["$or"] if q]

    if brand:
        query["brand"] = {"$regex": brand, "$options": "i"}
    if condition:
        query["condition"] = {"$regex": condition, "$options": "i"}
    if transmission:
        query["transmission"] = {"$regex": transmission, "$options": "i"}
    if fuel_type:
        query["fuelType"] = {"$regex": fuel_type, "$options": "i"}
    if color:
        query["color"] = {"$regex": color, "$options": "i"}
    if city:
        query["$or"] = query.get("$or", []) + [
            {"city": {"$regex": city, "$options": "i"}},
            {"state": {"$regex": city, "$options": "i"}},
        ]
    if min_price is not None:
        query.setdefault("sellingPrice", {})["$gte"] = min_price
    if max_price is not None:
        query.setdefault("sellingPrice", {})["$lte"] = max_price
    if year_from is not None:
        query.setdefault("year", {})["$gte"] = year_from
    if year_to is not None:
        query.setdefault("year", {})["$lte"] = year_to

    sort_field = "createdAt"
    sort_dir = -1
    if sort == "price_asc":
        sort_field, sort_dir = "sellingPrice", 1
    elif sort == "price_desc":
        sort_field, sort_dir = "sellingPrice", -1
    elif sort == "popular":
        sort_field, sort_dir = "viewCount", -1

    # Only show cars from approved dealers
    approved_dealers = await db["dealer_organizations"].find(
        {"status": "approved"}, {"_id": 1}
    ).to_list(10000)
    approved_ids = [str(d["_id"]) for d in approved_dealers]
    query["dealerId"] = {"$in": approved_ids}

    total = await db["car_listings"].count_documents(query)
    cars = await db["car_listings"].find(query).sort(sort_field, sort_dir).skip(skip).limit(limit).to_list(limit)

    result = []
    for car in cars:
        s = serialize_doc(car)
        dealer = await db["dealer_organizations"].find_one(
            {"_id": ObjectId(car["dealerId"])}
        ) if ObjectId.is_valid(car.get("dealerId", "")) else None
        if dealer:
            s["dealerName"] = dealer.get("companyName")
            s["dealerLogo"] = dealer.get("logo")
            s["dealerWhatsapp"] = dealer.get("whatsapp")
            s["dealerId"] = dealer.get("dealerId")
            s["state"] = car.get("state") or dealer.get("state")
        result.append(s)

    return {"total": total, "cars": result, "skip": skip, "limit": limit}


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
            "userId": dealer.get("userId"),
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

    return {"total": total, "dealers": [serialize_doc(d) for d in dealers]}


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
    result["userId"] = dealer.get("userId")
    follower_count = await db["follows"].count_documents({"dealerId": str(dealer["_id"])})
    result["followerCount"] = follower_count
    return result


# ── PUBLIC USER PROFILE ───────────────────────────────────────
# This is what the frontend /users/[userId] page calls

@router.get("/users/{user_id}")
async def public_user_profile(user_id: str):
    db = get_db()

    # Try by ObjectId (_id) first, then by userId string
    user = None
    if ObjectId.is_valid(user_id):
        user = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not user:
        user = await db["users"].find_one({"userId": user_id})

    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")

    # Return only safe public fields — never return passwordHash
    role = user.get("role", "USER")
    profile = {
        "_id": str(user["_id"]),
        "userId": str(user["_id"]),
        "fullName": user.get("fullName"),
        "role": role,
        "avatar": user.get("avatar") or user.get("profilePicture"),
        "city": user.get("city"),
        "state": user.get("state"),
        "bio": user.get("bio"),
        "phone": user.get("phone") if user.get("showPhone", True) else None,
        "whatsapp": user.get("whatsapp") if user.get("showWhatsapp", True) else None,
        "email": user.get("email") if user.get("showEmail", False) else None,
        "instagram": user.get("instagram"),
        "facebook": user.get("facebook"),
        "twitter": user.get("twitter"),
        "tiktok": user.get("tiktok"),
        "website": user.get("website"),
        "createdAt": user.get("createdAt"),
    }

    # Attach dealer info for DEALER_ADMIN and DEALER_STAFF
    if role in ("DEALER_ADMIN", "DEALER_STAFF"):
        dealer = None
        if role == "DEALER_ADMIN":
            dealer = await db["dealer_organizations"].find_one({"userId": str(user["_id"])})
        elif role == "DEALER_STAFF":
            staff = await db["staff_accounts"].find_one({"userId": str(user["_id"])})
            if staff and staff.get("dealerId"):
                dealer = await db["dealer_organizations"].find_one(
                    {"_id": ObjectId(staff["dealerId"])} if ObjectId.is_valid(staff["dealerId"])
                    else {"dealerId": staff["dealerId"]}
                )
        if dealer:
            profile["dealer"] = {
                "dealerId": dealer.get("dealerId"),
                "companyName": dealer.get("companyName"),
                "logo": dealer.get("logo"),
                "city": dealer.get("city"),
                "state": dealer.get("state"),
            }

    # Attach partner stats for PARTNER_USER
    if role == "PARTNER_USER":
        total_cars = await db["car_listings"].count_documents({"ownerId": str(user["_id"]), "ownerType": "partner"})
        total_dealers = await db["partner_links"].count_documents(
            {"partnerId": str(user["_id"]), "status": "approved"}
        ) if "partner_links" in await db.list_collection_names() else 0
        profile["stats"] = {"totalCars": total_cars, "totalDealers": total_dealers}

    return profile


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