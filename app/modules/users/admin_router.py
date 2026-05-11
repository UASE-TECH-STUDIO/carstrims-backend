from fastapi import APIRouter, Depends, Query, Body, UploadFile, File
from typing import Optional, List
from pydantic import BaseModel
from app.auth.dependencies import get_current_user
from app.modules.dealers.service import serialize_doc
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime
import random, string, cloudinary, cloudinary.uploader
from app.config.settings import settings

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
)


def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "SYSTEM_ADMIN":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


class BroadcastRequest(BaseModel):
    title: str
    message: str
    targetRole: str = "all"          # all, PUBLIC_USER, DEALER_ADMIN, PARTNER_USER, DEALER_STAFF
    allowReply: bool = False
    documentUrl: Optional[str] = None
    documentName: Optional[str] = None


router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


# ── STATS ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(admin=Depends(require_admin)):
    db = get_db()
    return {
        "totalDealers": await db["dealer_organizations"].count_documents({}),
        "activeDealers": await db["dealer_organizations"].count_documents({"status": "active"}),
        "pendingDealers": await db["dealer_organizations"].count_documents({"status": "pending"}),
        "totalUsers": await db["users"].count_documents({"role": "PUBLIC_USER"}),
        "totalPartners": await db["users"].count_documents({"role": "PARTNER_USER"}),
        "totalStaff": await db["staff_accounts"].count_documents({}),
        "totalCars": await db["car_listings"].count_documents({}),
        "totalSales": await db["sale_transactions"].count_documents({}),
    }


# ── DEALERS ───────────────────────────────────────────────────────────────────

@router.get("/dealers")
async def list_dealers(
    status: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(20),
    admin=Depends(require_admin),
):
    db = get_db()
    query = {}
    if status:
        query["status"] = status
    total = await db["dealer_organizations"].count_documents(query)
    dealers = await db["dealer_organizations"].find(query).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "dealers": [serialize_doc(d) for d in dealers]}


@router.post("/dealers/{dealer_id}/approve")
async def approve_dealer(dealer_id: str, admin=Depends(require_admin)):
    db = get_db()
    if ObjectId.is_valid(dealer_id):
        q = {"_id": ObjectId(dealer_id)}
    else:
        q = {"dealerId": dealer_id}
    dealer = await db["dealer_organizations"].find_one(q)
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")
    await db["dealer_organizations"].update_one(q, {"$set": {"status": "active", "approvedAt": datetime.utcnow()}})
    await db["users"].update_one({"_id": ObjectId(dealer["userId"])}, {"$set": {"status": "active"}})
    await db["notifications"].insert_one({
        "receiverId": dealer["userId"],
        "type": "general",
        "title": "Dealership Approved",
        "message": "Your dealership has been approved. You can now access your full dashboard.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })
    return {"message": "Dealer approved"}


@router.post("/dealers/{dealer_id}/reject")
async def reject_dealer(dealer_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    db = get_db()
    if ObjectId.is_valid(dealer_id):
        q = {"_id": ObjectId(dealer_id)}
    else:
        q = {"dealerId": dealer_id}
    dealer = await db["dealer_organizations"].find_one(q)
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")
    await db["dealer_organizations"].update_one(q, {"$set": {"status": "rejected"}})
    await db["users"].update_one({"_id": ObjectId(dealer["userId"])}, {"$set": {"status": "rejected"}})
    reason = data.get("reason", "Your application did not meet our requirements.")
    await db["notifications"].insert_one({
        "receiverId": dealer["userId"],
        "type": "general",
        "title": "Dealership Application Rejected",
        "message": reason,
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })
    return {"message": "Dealer rejected"}


# ── USERS ─────────────────────────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    role: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(20),
    search: Optional[str] = Query(None),
    admin=Depends(require_admin),
):
    db = get_db()
    query: dict = {}
    if role:
        query["role"] = role
    if search:
        query["$or"] = [
            {"fullName": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
        ]
    total = await db["users"].count_documents(query)
    users = await db["users"].find(query).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "users": [serialize_doc(u) for u in users]}


# ── BROADCAST ─────────────────────────────────────────────────────────────────

@router.post("/broadcast")
async def send_broadcast(data: BroadcastRequest, admin=Depends(require_admin)):
    db = get_db()
    admin_id = str(admin["_id"])

    # Find target users
    query: dict = {"status": "active"}
    if data.targetRole != "all":
        query["role"] = data.targetRole

    users = await db["users"].find(query, {"_id": 1}).to_list(10000)
    user_ids = [str(u["_id"]) for u in users]

    now = datetime.utcnow()
    broadcast_id = "BCAST-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

    # Insert notification for all target users
    if user_ids:
        notif_docs = [
            {
                "receiverId": uid,
                "senderId": admin_id,
                "type": "broadcast",
                "title": data.title,
                "message": data.message,
                "allowReply": data.allowReply,
                "documentUrl": data.documentUrl,
                "documentName": data.documentName,
                "broadcastId": broadcast_id,
                "isRead": False,
                "createdAt": now,
            }
            for uid in user_ids
        ]
        await db["notifications"].insert_many(notif_docs)

    # Also create message threads if allowReply=True
    if data.allowReply:
        # Create a conversation from admin to each user
        for uid in user_ids[:100]:  # limit to 100 for performance
            existing = await db["conversations"].find_one({
                "participants": {"$all": [admin_id, uid]},
                "type": "broadcast",
            })
            conv_id = f"CONV-{broadcast_id}-{uid[:6]}"
            if not existing:
                await db["conversations"].insert_one({
                    "conversationId": conv_id,
                    "participants": [admin_id, uid],
                    "type": "broadcast",
                    "lastMessage": data.message,
                    "lastMessageAt": now,
                    "createdAt": now,
                })
            await db["messages"].insert_one({
                "messageId": "MSG-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8)),
                "conversationId": conv_id,
                "senderId": admin_id,
                "receiverId": uid,
                "message": data.message,
                "isBroadcast": True,
                "allowReply": True,
                "documentUrl": data.documentUrl,
                "documentName": data.documentName,
                "isRead": False,
                "createdAt": now,
            })

    # Log the broadcast
    await db["broadcasts"].insert_one({
        "broadcastId": broadcast_id,
        "adminId": admin_id,
        "title": data.title,
        "message": data.message,
        "targetRole": data.targetRole,
        "recipientCount": len(user_ids),
        "allowReply": data.allowReply,
        "documentUrl": data.documentUrl,
        "documentName": data.documentName,
        "sentAt": now,
    })

    return {
        "message": f"Broadcast sent to {len(user_ids)} users",
        "broadcastId": broadcast_id,
        "recipientCount": len(user_ids),
    }


@router.get("/broadcasts")
async def get_broadcasts(
    skip: int = Query(0),
    limit: int = Query(20),
    admin=Depends(require_admin),
):
    db = get_db()
    total = await db["broadcasts"].count_documents({})
    docs = await db["broadcasts"].find({}).sort("sentAt", -1).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "broadcasts": [serialize_doc(d) for d in docs]}


# ── DOCUMENT UPLOAD FOR BROADCAST ─────────────────────────────────────────────

@router.post("/upload/document")
async def upload_broadcast_document(
    file: UploadFile = File(...),
    admin=Depends(require_admin),
):
    try:
        content = await file.read()
        result = cloudinary.uploader.upload(
            content,
            resource_type="raw",
            folder="carstrims/broadcast-docs",
            public_id=f"doc-{datetime.utcnow().timestamp()}",
            use_filename=True,
        )
        return {
            "url": result["secure_url"],
            "name": file.filename,
            "size": len(content),
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Upload failed: {str(e)}")


# ── ANALYTICS ─────────────────────────────────────────────────────────────────

@router.get("/analytics/growth")
async def analytics_growth(admin=Depends(require_admin)):
    db = get_db()
    # Simple monthly growth data
    pipeline = [
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m", "date": "$createdAt"}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
        {"$limit": 12},
    ]
    users_growth = await db["users"].aggregate(pipeline).to_list(12)
    dealers_growth = await db["dealer_organizations"].aggregate(pipeline).to_list(12)
    return {
        "usersGrowth": [{"month": d["_id"], "count": d["count"]} for d in users_growth],
        "dealersGrowth": [{"month": d["_id"], "count": d["count"]} for d in dealers_growth],
    }


@router.get("/activity")
async def activity_log(
    skip: int = Query(0),
    limit: int = Query(50),
    admin=Depends(require_admin),
):
    db = get_db()
    # Get recent notifications as activity proxy
    docs = await db["notifications"].find({}).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    return {"activities": [serialize_doc(d) for d in docs]}


@router.get("/top-dealers")
async def top_dealers(admin=Depends(require_admin)):
    db = get_db()
    pipeline = [
        {"$group": {"_id": "$dealerId", "totalSales": {"$sum": 1}, "totalRevenue": {"$sum": "$sellingPrice"}}},
        {"$sort": {"totalRevenue": -1}},
        {"$limit": 10},
    ]
    sales = await db["sale_transactions"].aggregate(pipeline).to_list(10)
    result = []
    for s in sales:
        if s["_id"] and ObjectId.is_valid(s["_id"]):
            dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(s["_id"])})
            if dealer:
                result.append({
                    "dealerName": dealer.get("companyName"),
                    "dealerId": dealer.get("dealerId"),
                    "totalSales": s["totalSales"],
                    "totalRevenue": s["totalRevenue"],
                })
    return result


@router.post("/create-dealer")
async def create_dealer_account(data: dict = Body(...), admin=Depends(require_admin)):
    from app.auth.password import hash_password
    db = get_db()

    email = data.get("email", "").lower()
    existing = await db["users"].find_one({"email": email})
    if existing:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Email already registered")

    temp_pass = data.get("password", "Dealer@" + "".join(random.choices(string.digits, k=6)))
    user_id = "USR-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    dealer_id = "DLR-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

    user_doc = {
        "userId": user_id,
        "fullName": data.get("fullName", ""),
        "username": data.get("username", email.split("@")[0]),
        "email": email,
        "passwordHash": hash_password(temp_pass),
        "phone": data.get("phone", ""),
        "role": "DEALER_ADMIN",
        "status": "active",
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }
    user_result = await db["users"].insert_one(user_doc)
    user_mongo_id = str(user_result.inserted_id)

    dealer_doc = {
        "dealerId": dealer_id,
        "userId": user_mongo_id,
        "companyName": data.get("companyName", data.get("fullName", "")),
        "ownerName": data.get("fullName", ""),
        "email": email,
        "phone": data.get("phone", ""),
        "city": data.get("city", ""),
        "state": data.get("state", ""),
        "status": "active",
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }
    await db["dealer_organizations"].insert_one(dealer_doc)

    return {
        "message": "Dealer created successfully",
        "dealerId": dealer_id,
        "tempPassword": temp_pass,
        "email": email,
    }