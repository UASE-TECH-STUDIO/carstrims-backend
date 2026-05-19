"""
Follow / Subscribe system
"""
from fastapi import APIRouter, Depends, Query
from app.auth.dependencies import get_current_user
from app.modules.dealers.service import serialize_doc
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime

router = APIRouter(prefix="/api/v1/follows", tags=["Follows"])


@router.post("/{dealer_id}")
async def follow_dealer(dealer_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])

    if ObjectId.is_valid(dealer_id):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    else:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})

    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")

    dealer_mongo_id = str(dealer["_id"])

    existing = await db["follows"].find_one({"userId": uid, "dealerId": dealer_mongo_id})
    if existing:
        count = await db["follows"].count_documents({"dealerId": dealer_mongo_id})
        return {"following": True, "followerCount": count, "message": "Already following"}

    await db["follows"].insert_one({
        "userId": uid,
        "dealerId": dealer_mongo_id,
        "dealerName": dealer.get("companyName"),
        "userEmail": current_user.get("email"),
        "userName": current_user.get("fullName"),
        "createdAt": datetime.utcnow(),
    })

    # Notify dealer — store actorName so overview activity works
    if dealer.get("userId"):
        actor_name = current_user.get("fullName", "Someone")
        await db["notifications"].insert_one({
            "receiverId": dealer["userId"],
            "senderId": uid,
            "actorId": uid,
            "actorName": actor_name,
            "type": "new_follower",
            "title": "New Follower",
            "message": f"{actor_name} started following your dealership.",
            "isRead": False,
            "data": {"userId": uid, "userName": actor_name},
            "createdAt": datetime.utcnow(),
        })

    count = await db["follows"].count_documents({"dealerId": dealer_mongo_id})
    return {"following": True, "followerCount": count, "message": f"Now following {dealer.get('companyName')}"}


@router.delete("/{dealer_id}")
async def unfollow_dealer(dealer_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])

    if ObjectId.is_valid(dealer_id):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    else:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})

    dealer_mongo_id = str(dealer["_id"]) if dealer else dealer_id
    await db["follows"].delete_one({"userId": uid, "dealerId": dealer_mongo_id})
    count = await db["follows"].count_documents({"dealerId": dealer_mongo_id})
    return {"following": False, "followerCount": count, "message": "Unfollowed"}


@router.get("/my")
async def my_follows(current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])
    follows = await db["follows"].find({"userId": uid}).sort("createdAt", -1).to_list(100)
    result = []
    for f in follows:
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(f["dealerId"])}) if ObjectId.is_valid(f.get("dealerId","")) else None
        if dealer:
            s = serialize_doc(dealer)
            s["followedAt"] = f.get("createdAt")
            result.append(s)
    return result


@router.get("/status/{dealer_id}")
async def follow_status(dealer_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])
    if ObjectId.is_valid(dealer_id):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    else:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})
    dealer_mongo_id = str(dealer["_id"]) if dealer else dealer_id
    existing = await db["follows"].find_one({"userId": uid, "dealerId": dealer_mongo_id})
    count = await db["follows"].count_documents({"dealerId": dealer_mongo_id})
    return {"following": bool(existing), "followerCount": count}


@router.get("/dealer/{dealer_id}/followers")
async def dealer_followers(
    dealer_id: str,
    skip: int = Query(0), limit: int = Query(50),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    if ObjectId.is_valid(dealer_id):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    else:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})
    if not dealer:
        return {"total": 0, "followers": []}
    dealer_mongo_id = str(dealer["_id"])
    total = await db["follows"].count_documents({"dealerId": dealer_mongo_id})
    follows = await db["follows"].find({"dealerId": dealer_mongo_id}).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "followers": [serialize_doc(f) for f in follows]}


@router.get("/{dealer_id}/followers")
async def dealer_followers_public(dealer_id: str, skip: int = Query(0), limit: int = Query(50)):
    db = get_db()
    if ObjectId.is_valid(dealer_id):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    else:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})
    if not dealer:
        return {"total": 0, "followers": []}
    dealer_mongo_id = str(dealer["_id"])
    total = await db["follows"].count_documents({"dealerId": dealer_mongo_id})
    follows = await db["follows"].find({"dealerId": dealer_mongo_id}).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    enriched = []
    for f in follows:
        user = await db["users"].find_one({"_id": ObjectId(f["userId"])}) if ObjectId.is_valid(f.get("userId","")) else None
        enriched.append({
            "userId": f.get("userId"),
            "fullName": f.get("userName") or (user.get("fullName") if user else "User"),
            "avatar": (user.get("avatar") or user.get("profilePicture")) if user else None,
            "role": user.get("role") if user else "PUBLIC_USER",
        })
    return {"total": total, "followers": enriched}
