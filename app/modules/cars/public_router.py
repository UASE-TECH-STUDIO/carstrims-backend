from fastapi import APIRouter, Depends, Query, Body
from typing import Optional
from app.auth.dependencies import get_current_user, get_current_dealer, get_current_dealer_or_staff
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
import time
import math
import hashlib


class CommentBody(BaseModel):
    text: str


class ReplyBody(BaseModel):
    text: str


router = APIRouter(prefix="/api/v1/public", tags=["Public Feed"])

# Simple short-lived cache: the set of approved dealer IDs barely changes
# (only when a dealer gets approved/suspended), yet it was being
# re-fetched — up to 10,000 documents — on EVERY single feed request.
# A short TTL cache turns that into one fetch per ~60 seconds shared
# across all users, instead of one fetch per request.
_approved_dealers_cache: dict = {"ids": None, "at": 0.0}
_APPROVED_DEALERS_TTL_SECONDS = 60


async def get_approved_dealer_ids(db) -> list:
    now = time.time()
    if _approved_dealers_cache["ids"] is not None and (now - _approved_dealers_cache["at"]) < _APPROVED_DEALERS_TTL_SECONDS:
        return _approved_dealers_cache["ids"]

    approved_dealers = await db["dealer_organizations"].find(
        {"status": "approved"}, {"_id": 1, "dealerId": 1}
    ).to_list(10000)
    approved_ids: list = []
    for d in approved_dealers:
        str_id = str(d["_id"])
        approved_ids.append(str_id)
        try:
            approved_ids.append(ObjectId(str_id))
        except Exception:
            pass
        if d.get("dealerId"):
            approved_ids.append(d["dealerId"])

    _approved_dealers_cache["ids"] = approved_ids
    _approved_dealers_cache["at"] = now
    return approved_ids


#  PUBLIC CAR FEED 

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
    seed: Optional[str] = Query(None, description="A per-session random seed from the frontend, so ordering stays stable while scrolling/paginating but changes on each fresh visit."),
):
    db = get_db()
    query: dict = {}

    if status and status != "all":
        query["status"] = status

    if search:
        # Smart search: recognize known vocabulary tokens (year,
        # condition, fuel type, transmission) as structured filters
        # extracted right out of free text — e.g. "camry 2019 used
        # automatic" becomes year=2019 AND condition~used AND
        # transmission~automatic, with "camry" left over as a plain
        # text match against brand/model/color/carId/description. This
        # replaces needing a separate filter UI for a lot of common
        # searches.
        CONDITION_WORDS = {"new": "new", "used": "used", "foreign": "foreign", "local": "local", "locally": "local", "salvage": "salvage"}
        FUEL_WORDS = {"petrol": "petrol", "diesel": "diesel", "electric": "electric", "hybrid": "hybrid", "gas": "gas"}
        TRANSMISSION_WORDS = {"automatic": "automatic", "manual": "manual", "cvt": "cvt", "semi-automatic": "semi-automatic"}
        STATUS_WORDS = {"available": "available", "sold": "sold"}
        STATE_WORDS = {s.lower(): s for s in ["Abuja","Lagos","Kano","Rivers","Oyo","Kaduna","Anambra","Enugu","Delta","Ogun","Imo","Ondo","Kwara","Benue","Edo","Ekiti","Cross River"]}

        tokens = search.strip().split()
        leftover_tokens = []
        smart_filters: list = []

        for tok in tokens:
            low = tok.lower()
            if low.isdigit() and len(low) == 4 and 1980 <= int(low) <= 2035:
                smart_filters.append({"year": int(low)})
            elif low in CONDITION_WORDS:
                smart_filters.append({"condition": {"$regex": CONDITION_WORDS[low], "$options": "i"}})
            elif low in FUEL_WORDS:
                smart_filters.append({"fuelType": {"$regex": FUEL_WORDS[low], "$options": "i"}})
            elif low in TRANSMISSION_WORDS:
                smart_filters.append({"transmission": {"$regex": TRANSMISSION_WORDS[low], "$options": "i"}})
            elif low in STATUS_WORDS:
                query["status"] = STATUS_WORDS[low]  # overrides the default "available" status param
            elif low in STATE_WORDS:
                smart_filters.append({"state": {"$regex": STATE_WORDS[low], "$options": "i"}})
            else:
                leftover_tokens.append(tok)

        if smart_filters:
            query["$and"] = query.get("$and", []) + smart_filters

        leftover = " ".join(leftover_tokens).strip()
        if leftover:
            query["$or"] = [
                {"brand": {"$regex": leftover, "$options": "i"}},
                {"model": {"$regex": leftover, "$options": "i"}},
                {"color": {"$regex": leftover, "$options": "i"}},
                {"carId": {"$regex": leftover, "$options": "i"}},
                {"description": {"$regex": leftover, "$options": "i"}},
            ]

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

    # Only show cars from approved dealers in the public feed
    approved_ids = await get_approved_dealer_ids(db)
    if approved_ids:
        query["dealerId"] = {"$in": approved_ids}

    total = await db["car_listings"].count_documents(query)

    if sort == "score":
        # Personalized-feeling feed: recency + engagement scoring, like
        # before, but reworked in two important ways:
        #
        # 1. The randomness is now a deterministic hash of (seed, carId)
        #    instead of MongoDB's $rand, which re-evaluates on every
        #    request — with pagination (skip/limit), that could cause
        #    the same car to appear twice, or another to get skipped
        #    entirely, as the "random" order silently shifted between
        #    page 1 and page 2 of the same scroll session. The frontend
        #    generates one seed per fresh visit/refresh (not per
        #    scroll-fetch) and sends it with every page, so ordering is
        #    now fully stable while scrolling, but genuinely different
        #    each time the app is opened or refreshed — and different
        #    seeds naturally land differently per person too.
        #
        # 2. Dealer-diversity interleaving: cars are grouped by dealer
        #    (each dealer's own cars keep their relative score order),
        #    then taken round-robin across dealers — so one dealer
        #    posting a lot doesn't dominate several consecutive feed
        #    slots, while dealers with generally higher-scoring cars
        #    still get interleaved earlier in each round.
        candidates = await db["car_listings"].find(query).sort("createdAt", -1).limit(500).to_list(500)

        now = datetime.utcnow()
        effective_seed = seed or "default-seed"

        for c in candidates:
            created = c.get("createdAt") or now
            try:
                age_hours = max(0.0, (now - created).total_seconds() / 3600)
            except TypeError:
                age_hours = 0.0
            recency = 10000.0 if age_hours <= 2 else 100.0 * math.exp(-0.008 * age_hours)
            engagement = (c.get("viewCount", 0) or 0) * 0.3 + (c.get("likeCount", 0) or 0) * 2.0
            h = hashlib.md5(f"{effective_seed}:{c.get('carId','')}".encode()).hexdigest()
            jitter = (int(h[:8], 16) / 0xFFFFFFFF) * 15
            c["_feedScore"] = recency + engagement + jitter

        candidates.sort(key=lambda c: c["_feedScore"], reverse=True)

        by_dealer: dict = {}
        dealer_order: list = []
        for c in candidates:
            did = c.get("dealerId", "unknown")
            if did not in by_dealer:
                by_dealer[did] = []
                dealer_order.append(did)
            by_dealer[did].append(c)

        interleaved: list = []
        while any(by_dealer[d] for d in dealer_order):
            for d in dealer_order:
                if by_dealer[d]:
                    interleaved.append(by_dealer[d].pop(0))

        cars = interleaved[skip:skip + limit]
    else:
        cars = await db["car_listings"].find(query).sort(sort_field, sort_dir).skip(skip).limit(limit).to_list(limit)

    # Batch-fetch dealer info for this page in ONE query instead of one
    # query per car (was 20 sequential database round-trips per page —
    # the main cause of the feed feeling slow to load).
    page_dealer_ids = list({
        car["dealerId"] for car in cars
        if ObjectId.is_valid(car.get("dealerId", ""))
    })
    dealers_by_id = {}
    if page_dealer_ids:
        dealer_docs = await db["dealer_organizations"].find(
            {"_id": {"$in": [ObjectId(d) for d in page_dealer_ids]}}
        ).to_list(len(page_dealer_ids))
        dealers_by_id = {str(d["_id"]): d for d in dealer_docs}

    result = []
    for car in cars:
        s = serialize_doc(car)
        dealer = dealers_by_id.get(car.get("dealerId"))
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


@router.get("/search")
async def universal_search(
    q: str = Query(..., min_length=1),
    types: Optional[str] = Query(None, description="Comma-separated: cars,dealers,users. Default: all."),
    limit: int = Query(8, le=30),
):
    """
    One search box, everything on the platform: cars (by brand, model,
    year, color, or car ID), dealers (by company/owner name or city),
    and users (by name or username — covers regular users, partners,
    and buyers, since they're all in the same users collection).
    Returns a small number of results per category, meant for a quick
    "search everything" overview rather than deep pagination.
    """
    db = get_db()
    want = set((types.split(",") if types else ["cars", "dealers", "users"]))
    results: dict = {}

    if "cars" in want:
        car_or = [
            {"brand": {"$regex": q, "$options": "i"}},
            {"model": {"$regex": q, "$options": "i"}},
            {"color": {"$regex": q, "$options": "i"}},
            {"carId": {"$regex": q, "$options": "i"}},
        ]
        if q.strip().isdigit():
            car_or.append({"year": int(q.strip())})
        cars = await db["car_listings"].find(
            {"$or": car_or, "status": {"$in": ["available", "sold"]}}
        ).sort("createdAt", -1).limit(limit).to_list(limit)
        results["cars"] = [serialize_doc(c) for c in cars]

    if "dealers" in want:
        dealers = await db["dealer_organizations"].find({
            "status": "approved",
            "$or": [
                {"companyName": {"$regex": q, "$options": "i"}},
                {"ownerName": {"$regex": q, "$options": "i"}},
                {"city": {"$regex": q, "$options": "i"}},
            ],
        }).limit(limit).to_list(limit)
        results["dealers"] = [serialize_doc(d) for d in dealers]

    if "users" in want:
        users = await db["users"].find(
            {
                "status": {"$ne": "suspended"},
                "$or": [
                    {"fullName": {"$regex": q, "$options": "i"}},
                    {"username": {"$regex": q, "$options": "i"}},
                ],
            },
            {"passwordHash": 0},  # never expose this, even hashed
        ).limit(limit).to_list(limit)
        results["users"] = [serialize_doc(u) for u in users]

    return results


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

    # Add social links from dealer owner's user profile if not already on dealer doc
    if dealer.get("userId"):
        owner = None
        if ObjectId.is_valid(str(dealer["userId"])):
            owner = await db["users"].find_one({"_id": ObjectId(str(dealer["userId"]))})
        if not owner:
            owner = await db["users"].find_one({"userId": str(dealer["userId"])})
        if owner:
            for field in ["instagram", "facebook", "twitter", "tiktok", "youtube", "website", "phone", "whatsapp", "email"]:
                if not result.get(field) and owner.get(field):
                    result[field] = owner.get(field)

    return result


#  PUBLIC USER PROFILE 
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

    # Return only safe public fields  never return passwordHash
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


#  QR CODE 

@router.post("/qr/generate")
async def generate_qr(current_user: dict = Depends(get_current_dealer_or_staff)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    frontend_url = settings.FRONTEND_URL
    return await generate_dealer_qr(dealer["_id"], frontend_url)


@router.get("/qr/me")
async def get_my_qr(current_user: dict = Depends(get_current_dealer_or_staff)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await get_dealer_qr(dealer["_id"])


@router.get("/qr/{dealer_id}")
async def get_dealer_qr_public(dealer_id: str):
    return await get_dealer_qr(dealer_id)


#  LIKES 

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


#  COMMENTS 

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
    is_admin = current_user.get("role") == "SYSTEM_ADMIN"
    return await delete_comment(comment_id, str(current_user["_id"]), is_admin=is_admin)



@router.get("/debug-feed")
async def debug_feed():
    """Debug: show exactly what dealers and cars the feed returns."""
    db = get_db()
    approved = await db["dealer_organizations"].find(
        {"status": "approved"}, {"_id": 1, "dealerId": 1, "companyName": 1}
    ).to_list(50)

    result = []
    for d in approved:
        str_id = str(d["_id"])
        # Count cars with string id
        cars_str = await db["car_listings"].count_documents(
            {"dealerId": str_id, "status": "available"}
        )
        # Count cars with ObjectId
        cars_oid = await db["car_listings"].count_documents(
            {"dealerId": ObjectId(str_id), "status": "available"}
        ) if ObjectId.is_valid(str_id) else 0
        # Get sample
        sample = await db["car_listings"].find(
            {"status": "available"},
            {"carId": 1, "brand": 1, "dealerId": 1}
        ).limit(3).to_list(3)

        result.append({
            "company": d.get("companyName"),
            "mongo_id": str_id,
            "dealerId_field": d.get("dealerId"),
            "cars_matching_string_id": cars_str,
            "cars_matching_objectid": cars_oid,
            "sample_cars_in_db": [
                {"carId": c.get("carId"), "dealerId": str(c.get("dealerId"))}
                for c in sample
            ],
        })

    return {"approved_dealers": result, "total_approved": len(result)}


@router.post("/cars/{car_id}/comments/{comment_id}/reply")
async def reply_comment(
    car_id: str,
    comment_id: str,
    body: ReplyBody,
    current_user: dict = Depends(get_current_user),
):
    return await add_reply(str(current_user["_id"]), comment_id, body.text)