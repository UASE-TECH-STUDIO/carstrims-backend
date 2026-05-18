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
    targetRole: str = "all"
    targetUserIds: Optional[List[str]] = None   # specific users
    documentUrl: Optional[str] = None
    documentName: Optional[str] = None
    documentType: Optional[str] = None           # "image" | "video" | "document"


router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


# â”€â”€ STATS (corrected role counts) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.get("/stats")
async def get_stats(admin=Depends(require_admin)):
    db = get_db()
    total_dealers    = await db["dealer_organizations"].count_documents({})
    active_dealers   = await db["dealer_organizations"].count_documents({"status": "approved"})
    pending_dealers  = await db["dealer_organizations"].count_documents({"status": "awaiting_approval"})
    suspended_dealers= await db["dealer_organizations"].count_documents({"status": "suspended"})

    # Correct role-based user counts
    total_users      = await db["users"].count_documents({})
    buyers_only      = await db["users"].count_documents({"role": "PUBLIC_USER"})
    partners_only    = await db["users"].count_documents({"role": "PARTNER_USER"})
    staff_only       = await db["users"].count_documents({"role": "DEALER_STAFF"})
    dealer_admins    = await db["users"].count_documents({"role": "DEALER_ADMIN"})

    total_cars  = await db["car_listings"].count_documents({})
    total_sold  = await db["car_listings"].count_documents({"status": "sold"})

    rev = await db["sale_transactions"].aggregate([
        {"$group": {"_id": None, "total": {"$sum": "$sellingPrice"}, "count": {"$sum": 1}}}
    ]).to_list(1)

    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_dealers = await db["dealer_organizations"].count_documents({"createdAt": {"$gte": month_start}})
    month_sales = await db["sale_transactions"].aggregate([
        {"$match": {"soldAt": {"$gte": month_start}}},
        {"$group": {"_id": None, "total": {"$sum": "$sellingPrice"}, "count": {"$sum": 1}}},
    ]).to_list(1)

    return {
        "dealers": {
            "total": total_dealers, "active": active_dealers,
            "pending": pending_dealers, "suspended": suspended_dealers,
            "thisMonth": month_dealers,
        },
        "users": {
            "total": total_users,
            "buyers": buyers_only,
            "partners": partners_only,
            "staff": staff_only,
            "dealerAdmins": dealer_admins,
        },
        "inventory": {"totalCars": total_cars, "totalSold": total_sold},
        "revenue": {
            "allTime": rev[0]["total"] if rev else 0,
            "thisMonth": month_sales[0]["total"] if month_sales else 0,
            "totalTransactions": rev[0]["count"] if rev else 0,
            "monthTransactions": month_sales[0]["count"] if month_sales else 0,
        },
    }


# â”€â”€ DEALERS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.get("/dealers")
async def list_dealers(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0), limit: int = Query(20),
    admin=Depends(require_admin),
):
    db = get_db()
    query = {}
    if status and status != "all": query["status"] = status
    if search:
        query["$or"] = [
            {"companyName": {"$regex": search, "$options": "i"}},
            {"ownerName": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"dealerId": {"$regex": search, "$options": "i"}},
        ]
    total = await db["dealer_organizations"].count_documents(query)
    dealers = await db["dealer_organizations"].find(query).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    enriched = []
    for d in dealers:
        s = serialize_doc(d)
        s["staffCount"] = await db["staff_accounts"].count_documents({"dealerId": str(d["_id"])})
        s["carCount"] = await db["car_listings"].count_documents({"dealerId": str(d["_id"])})
        s["soldCount"] = await db["car_listings"].count_documents({"dealerId": str(d["_id"]), "status": "sold"})
        enriched.append(s)
    return {"total": total, "dealers": enriched}


@router.post("/dealers/{dealer_id}/approve")
async def approve_dealer(dealer_id: str, admin=Depends(require_admin)):
    db = get_db()
    q = {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
    dealer = await db["dealer_organizations"].find_one(q)
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")
    await db["dealer_organizations"].update_one(q, {"$set": {"status": "approved", "approvedAt": datetime.utcnow()}})
    await db["users"].update_one({"_id": ObjectId(dealer["userId"])}, {"$set": {"status": "active"}})
    await db["notifications"].insert_one({
        "receiverId": dealer["userId"], "type": "general",
        "title": "Dealership Approved âœ…",
        "message": "Your dealership has been approved. You now have full access to your dashboard.",
        "isRead": False, "createdAt": datetime.utcnow(),
    })
    return {"message": "Dealer approved"}


@router.post("/dealers/{dealer_id}/reject")
async def reject_dealer(dealer_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    db = get_db()
    q = {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
    dealer = await db["dealer_organizations"].find_one(q)
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")
    reason = data.get("reason", "Your application did not meet our requirements.")
    await db["dealer_organizations"].update_one(q, {"$set": {"status": "rejected", "warningNote": reason}})
    await db["users"].update_one({"_id": ObjectId(dealer["userId"])}, {"$set": {"status": "rejected"}})
    await db["notifications"].insert_one({
        "receiverId": dealer["userId"], "type": "general",
        "title": "Application Rejected", "message": reason,
        "isRead": False, "createdAt": datetime.utcnow(),
    })
    return {"message": "Dealer rejected"}


@router.post("/dealers/{dealer_id}/suspend")
async def suspend_dealer(dealer_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    db = get_db()
    q = {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
    dealer = await db["dealer_organizations"].find_one(q)
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")
    note = data.get("note", "Your account has been suspended.")
    await db["dealer_organizations"].update_one(q, {"$set": {"status": "suspended", "warningNote": note, "updatedAt": datetime.utcnow()}})
    await db["users"].update_one({"_id": ObjectId(dealer["userId"])}, {"$set": {"status": "suspended"}})
    await db["notifications"].insert_one({
        "receiverId": dealer["userId"], "type": "general",
        "title": "Account Suspended â›”", "message": note,
        "isRead": False, "createdAt": datetime.utcnow(),
    })
    return {"message": "Dealer suspended"}


@router.post("/dealers/{dealer_id}/warn")
async def warn_dealer(dealer_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    db = get_db()
    q = {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
    dealer = await db["dealer_organizations"].find_one(q)
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")
    note = data.get("note", "Please review your account activity.")
    await db["dealer_organizations"].update_one(q, {"$set": {"warningNote": note, "updatedAt": datetime.utcnow()}})
    await db["notifications"].insert_one({
        "receiverId": dealer["userId"], "type": "general",
        "title": "Account Warning âš ï¸", "message": note,
        "isRead": False, "createdAt": datetime.utcnow(),
    })
    return {"message": "Warning sent"}


@router.delete("/dealers/{dealer_id}")
async def delete_dealer(dealer_id: str, admin=Depends(require_admin)):
    db = get_db()
    q = {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
    dealer = await db["dealer_organizations"].find_one(q)
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")
    await db["dealer_organizations"].update_one(q, {"$set": {"status": "deleted", "updatedAt": datetime.utcnow()}})
    await db["users"].update_one({"_id": ObjectId(dealer["userId"])}, {"$set": {"status": "deleted"}})
    return {"message": "Dealer deleted"}


@router.post("/dealers/{user_id}/reset-password")
async def reset_dealer_password(user_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    from app.auth.password import hash_password
    db = get_db()
    new_password = data.get("newPassword", "Reset@" + "".join(random.choices(string.digits + string.ascii_letters, k=8)))
    if ObjectId.is_valid(user_id):
        await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": {"passwordHash": hash_password(new_password)}})
    return {"message": "Password reset", "newPassword": new_password}


# â”€â”€ USERS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.get("/users")
async def list_users(
    role: Optional[str] = Query(None),
    skip: int = Query(0), limit: int = Query(20),
    search: Optional[str] = Query(None),
    admin=Depends(require_admin),
):
    db = get_db()
    query: dict = {}
    if role and role != "all": query["role"] = role
    if search:
        query["$or"] = [
            {"fullName": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"username": {"$regex": search, "$options": "i"}},
        ]
    total = await db["users"].count_documents(query)
    users = await db["users"].find(query).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    clean = []
    for u in users:
        s = serialize_doc(u)
        s.pop("passwordHash", None)
        clean.append(s)
    return {"total": total, "users": clean}


@router.post("/users/{user_id}/suspend")
async def suspend_user(user_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    db = get_db()
    reason = data.get("reason", "Your account has been suspended.")
    await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": {"status": "suspended", "updatedAt": datetime.utcnow()}})
    await db["notifications"].insert_one({
        "receiverId": user_id, "type": "general",
        "title": "Account Suspended â›”", "message": reason,
        "isRead": False, "createdAt": datetime.utcnow(),
    })
    return {"message": "User suspended"}


@router.post("/users/{user_id}/unsuspend")
async def unsuspend_user(user_id: str, admin=Depends(require_admin)):
    db = get_db()
    await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": {"status": "active", "updatedAt": datetime.utcnow()}})
    await db["notifications"].insert_one({
        "receiverId": user_id, "type": "general",
        "title": "Account Reactivated âœ…",
        "message": "Your account has been reactivated. Welcome back!",
        "isRead": False, "createdAt": datetime.utcnow(),
    })
    return {"message": "User unsuspended"}


@router.post("/users/{user_id}/warn")
async def warn_user(user_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    db = get_db()
    reason = data.get("reason", "Please review your account activity.")
    await db["notifications"].insert_one({
        "receiverId": user_id, "type": "general",
        "title": "Account Warning âš ï¸", "message": reason,
        "isRead": False, "createdAt": datetime.utcnow(),
    })
    return {"message": "Warning sent"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin=Depends(require_admin)):
    db = get_db()
    await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": {"status": "deleted", "updatedAt": datetime.utcnow()}})
    return {"message": "User deleted"}


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    from app.auth.password import hash_password
    db = get_db()
    new_password = data.get("newPassword", "Reset@" + "".join(random.choices(string.digits + string.ascii_letters, k=8)))
    await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": {"passwordHash": hash_password(new_password)}})
    return {"message": "Password reset", "newPassword": new_password}


# â”€â”€ CAR MODERATION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.delete("/cars/{car_id}")
async def admin_delete_car(car_id: str, admin=Depends(require_admin)):
    db = get_db()
    query = {"_id": ObjectId(car_id)} if ObjectId.is_valid(car_id) else {"carId": car_id}
    car = await db["car_listings"].find_one(query)
    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Car listing not found")
    await db["admin_deletion_logs"].insert_one({
        "type": "car_listing", "carId": car.get("carId"),
        "brand": car.get("brand"), "model": car.get("model"),
        "dealerId": car.get("dealerId"), "deletedBy": str(admin["_id"]),
        "deletedAt": datetime.utcnow(), "reason": "Admin moderation",
    })
    await db["car_listings"].delete_one({"_id": car["_id"]})
    await db["comments"].delete_many({"carId": car.get("carId")})
    if car.get("dealerId") and ObjectId.is_valid(car["dealerId"]):
        await db["dealer_organizations"].update_one(
            {"_id": ObjectId(car["dealerId"])}, {"$inc": {"totalCarsListed": -1}}
        )
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(car["dealerId"])})
        if dealer and dealer.get("userId"):
            await db["notifications"].insert_one({
                "receiverId": dealer["userId"], "type": "general",
                "title": "Car Listing Removed",
                "message": f"Your listing for {car.get('brand','')} {car.get('model','')} was removed by a platform admin.",
                "isRead": False, "createdAt": datetime.utcnow(),
            })
    return {"message": "Car listing deleted", "carId": car.get("carId")}


@router.delete("/cars/{car_id}/comments/{comment_id}")
async def admin_delete_comment(car_id: str, comment_id: str, admin=Depends(require_admin)):
    db = get_db()
    query = {"_id": ObjectId(comment_id)} if ObjectId.is_valid(comment_id) else {"commentId": comment_id}
    comment = await db["comments"].find_one(query)
    if not comment:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Comment not found")
    await db["comments"].delete_one({"_id": comment["_id"]})
    return {"message": "Comment deleted"}


# â”€â”€ BROADCAST (with specific user targeting + video) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.post("/broadcast")
async def send_broadcast(data: BroadcastRequest, admin=Depends(require_admin)):
    db = get_db()
    admin_id = str(admin["_id"])
    now = datetime.utcnow()
    broadcast_id = "BCAST-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    system_user = await db["users"].find_one({"role": "SYSTEM_ADMIN"})
    system_id = str(system_user["_id"]) if system_user else admin_id

    # Resolve recipients
    if data.targetUserIds and len(data.targetUserIds) > 0:
        user_ids = data.targetUserIds
    else:
        query: dict = {}
        if data.targetRole != "all":
            query["role"] = data.targetRole
        users = await db["users"].find(query, {"_id": 1}).to_list(50000)
        user_ids = [str(u["_id"]) for u in users]

    if not user_ids:
        return {"message": "No recipients found", "sentTo": 0}

    # Send announcement message to each recipient
    msg_docs = []
    conv_docs = []
    notif_docs = []

    for uid in user_ids:
        conv_id = f"BCAST-{broadcast_id}-{uid[-8:]}"
        msg_docs.append({
            "messageId": "MSG-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10)),
            "conversationId": conv_id,
            "senderId": system_id,
            "receiverId": uid,
            "type": "announcement",
            "title": data.title,
            "message": data.message,
            "attachmentUrl": data.documentUrl,
            "attachmentName": data.documentName,
            "attachmentType": data.documentType,  # "image"|"video"|"document"
            "broadcastId": broadcast_id,
            "isRead": False,
            "createdAt": now,
        })
        conv_docs.append({
            "conversationId": conv_id,
            "participants": [system_id, uid],
            "type": "announcement",
            "isBroadcast": True,
            "lastMessage": data.title,
            "lastMessageAt": now,
            "unreadCount": 1,
            "createdAt": now,
        })
        notif_docs.append({
            "receiverId": uid, "senderId": system_id,
            "type": "announcement",
            "title": data.title,
            "message": data.message[:120],
            "attachmentUrl": data.documentUrl,
            "broadcastId": broadcast_id,
            "isRead": False,
            "createdAt": now,
        })

    if msg_docs:
        await db["messages"].insert_many(msg_docs)
    if conv_docs:
        await db["conversations"].insert_many(conv_docs)
    if notif_docs:
        await db["notifications"].insert_many(notif_docs)

    await db["broadcasts"].insert_one({
        "broadcastId": broadcast_id, "adminId": admin_id,
        "title": data.title, "message": data.message,
        "targetRole": data.targetRole,
        "targetUserIds": data.targetUserIds or [],
        "recipientCount": len(user_ids),
        "attachmentUrl": data.documentUrl,
        "attachmentName": data.documentName,
        "attachmentType": data.documentType,
        "sentAt": now,
    })

    return {
        "message": f"Broadcast sent to {len(user_ids)} users",
        "broadcastId": broadcast_id,
        "sentTo": len(user_ids),
    }


@router.get("/broadcasts")
async def get_broadcasts(skip: int = Query(0), limit: int = Query(20), admin=Depends(require_admin)):
    db = get_db()
    total = await db["broadcasts"].count_documents({})
    docs = await db["broadcasts"].find({}).sort("sentAt", -1).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "broadcasts": [serialize_doc(d) for d in docs]}


# â”€â”€ UPLOAD (image, video, document) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.post("/upload/document")
async def upload_broadcast_attachment(file: UploadFile = File(...), admin=Depends(require_admin)):
    try:
        content = await file.read()
        content_type = file.content_type or ""
        if content_type.startswith("image/"):
            resource_type = "image"
            doc_type = "image"
        elif content_type.startswith("video/"):
            resource_type = "video"
            doc_type = "video"
        else:
            resource_type = "raw"
            doc_type = "document"

        result = cloudinary.uploader.upload(
            content, resource_type=resource_type,
            folder="carstrims/broadcast-attachments",
            use_filename=True,
        )
        return {
            "url": result["secure_url"],
            "name": file.filename,
            "size": len(content),
            "type": doc_type,         # "image" | "video" | "document"
            "isImage": doc_type == "image",
            "isVideo": doc_type == "video",
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Upload failed: {str(e)}")


# â”€â”€ ANALYTICS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.get("/growth")
async def analytics_growth(admin=Depends(require_admin)):
    db = get_db()
    now = datetime.utcnow()
    months = []
    for i in range(5, -1, -1):
        month_offset = now.month - i
        year = now.year
        while month_offset <= 0:
            month_offset += 12; year -= 1
        start = datetime(year, month_offset, 1)
        end = datetime(year + 1, 1, 1) if month_offset == 12 else datetime(year, month_offset + 1, 1)
        label = start.strftime("%b")
        new_dealers = await db["dealer_organizations"].count_documents({"createdAt": {"$gte": start, "$lt": end}})
        new_users = await db["users"].count_documents({"createdAt": {"$gte": start, "$lt": end}})
        sales_result = await db["sale_transactions"].aggregate([
            {"$match": {"soldAt": {"$gte": start, "$lt": end}}},
            {"$group": {"_id": None, "revenue": {"$sum": "$sellingPrice"}, "count": {"$sum": 1}}},
        ]).to_list(1)
        months.append({
            "month": label, "newDealers": new_dealers, "newUsers": new_users,
            "revenue": sales_result[0]["revenue"] if sales_result else 0,
            "sales": sales_result[0]["count"] if sales_result else 0,
        })
    return months


@router.get("/top-dealers")
async def top_dealers(limit: int = Query(10), admin=Depends(require_admin)):
    db = get_db()
    dealers = await db["dealer_organizations"].find({"status": "approved"}).sort("totalCarsSold", -1).limit(limit).to_list(limit)
    result = []
    for i, d in enumerate(dealers):
        s = serialize_doc(d); s["rank"] = i + 1; result.append(s)
    return result


@router.get("/activity")
async def activity_log(skip: int = Query(0), limit: int = Query(50), admin=Depends(require_admin)):
    db = get_db()
    docs = await db["notifications"].find({}).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    return {"activities": [serialize_doc(d) for d in docs]}


# â”€â”€ CREATE DEALER â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.post("/create-dealer")
async def create_dealer_account(data: dict = Body(...), admin=Depends(require_admin)):
    from app.auth.password import hash_password
    db = get_db()
    email = data.get("email", "").lower()
    existing = await db["users"].find_one({"email": email})
    if existing:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Email already registered")
    password = data.get("password", "Dealer@" + "".join(random.choices(string.digits, k=6)))
    user_doc = {
        "fullName": data.get("fullName"), "username": data.get("username", email.split("@")[0]),
        "email": email, "phone": data.get("phone", ""), "role": "DEALER_ADMIN",
        "passwordHash": hash_password(password), "status": "active",
        "dealerId": None, "isEmailVerified": True,
        "createdAt": datetime.utcnow(), "updatedAt": datetime.utcnow(),
    }
    user_result = await db["users"].insert_one(user_doc)
    user_id = str(user_result.inserted_id)
    dealer_doc = {
        "dealerId": "DLR-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8)),
        "userId": user_id, "companyName": data.get("companyName", data.get("fullName")),
        "ownerName": data.get("fullName"), "email": email, "phone": data.get("phone", ""),
        "city": data.get("city", ""), "state": data.get("state", ""), "country": "Nigeria",
        "status": "approved", "approvedAt": datetime.utcnow(), "approvedBy": str(admin["_id"]),
        "subscriptionPlan": "free", "totalCarsListed": 0, "totalCarsSold": 0, "totalRevenue": 0.0,
        "createdAt": datetime.utcnow(), "updatedAt": datetime.utcnow(),
    }
    dealer_result = await db["dealer_organizations"].insert_one(dealer_doc)
    await db["users"].update_one({"_id": user_result.inserted_id}, {"$set": {"dealerId": str(dealer_result.inserted_id)}})
    return {"message": "Dealer created", "dealerId": dealer_doc["dealerId"], "email": email, "tempPassword": password}


# ── ADMIN: VIEW/EDIT ANY USER PROFILE ────────────────────────
@router.get("/users/{user_id}/profile")
async def admin_get_user_profile(user_id: str, admin=Depends(require_admin)):
    db = get_db()
    from bson import ObjectId
    user = await db["users"].find_one({"_id": ObjectId(user_id)}) if ObjectId.is_valid(user_id) else None
    if not user:
        user = await db["users"].find_one({"userId": user_id})
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")
    s = serialize_doc(user)
    s.pop("passwordHash", None)
    # Attach dealer info if dealer
    if user.get("role") in ("DEALER_ADMIN", "DEALER_STAFF"):
        dealer = await db["dealer_organizations"].find_one({"userId": user_id})
        if dealer:
            s["dealer"] = serialize_doc(dealer)
    return s


@router.patch("/users/{user_id}/profile")
async def admin_update_user_profile(
    user_id: str,
    data: dict = Body({}),
    admin=Depends(require_admin),
):
    """Admin can update any field on a user's profile."""
    db = get_db()
    forbidden = {"passwordHash", "_id", "role"}
    update = {k: v for k, v in data.items() if k not in forbidden}
    update["updatedAt"] = datetime.utcnow()
    await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": update})
    user = await db["users"].find_one({"_id": ObjectId(user_id)})
    s = serialize_doc(user)
    s.pop("passwordHash", None)
    return s


@router.post("/users/{user_id}/restrict-profile-field")
async def admin_restrict_profile_field(
    user_id: str,
    data: dict = Body({}),
    admin=Depends(require_admin),
):
    """Mark a user's public profile field as restricted (hidden from public)."""
    db = get_db()
    field = data.get("field")
    reason = data.get("reason", "Restricted by platform admin")
    if not field:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="field is required")
    restricted_key = f"restricted_{field}"
    await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {restricted_key: True, f"restrictReason_{field}": reason, "updatedAt": datetime.utcnow()}}
    )
    # Notify user
    await db["notifications"].insert_one({
        "receiverId": user_id, "type": "general",
        "title": "Profile Field Restricted",
        "message": f"Your profile field '{field}' has been restricted: {reason}. Please update it from your settings.",
        "isRead": False, "createdAt": datetime.utcnow(),
    })
    return {"message": f"Field '{field}' restricted", "reason": reason}


@router.post("/users/{user_id}/unrestrict-profile-field")
async def admin_unrestrict_profile_field(
    user_id: str,
    data: dict = Body({}),
    admin=Depends(require_admin),
):
    db = get_db()
    field = data.get("field")
    await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$unset": {f"restricted_{field}": "", f"restrictReason_{field}": ""}, "$set": {"updatedAt": datetime.utcnow()}}
    )
    return {"message": f"Field '{field}' unrestricted"}


# ── ADMIN: VIEW/EDIT DEALER SETUP DOCS (even after approval) ─
@router.get("/dealers/{dealer_id}/setup")
async def admin_get_dealer_setup(dealer_id: str, admin=Depends(require_admin)):
    db = get_db()
    q = {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
    dealer = await db["dealer_organizations"].find_one(q)
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")
    s = serialize_doc(dealer)
    user = await db["users"].find_one({"_id": ObjectId(dealer["userId"])})
    if user:
        us = serialize_doc(user)
        us.pop("passwordHash", None)
        s["ownerUser"] = us
    return s


@router.patch("/dealers/{dealer_id}/setup")
async def admin_update_dealer_setup(
    dealer_id: str,
    data: dict = Body({}),
    admin=Depends(require_admin),
):
    """Admin can update/attach any dealer setup field including logo, passport, ID, CAC."""
    db = get_db()
    q = {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
    data["updatedAt"] = datetime.utcnow()
    data.pop("_id", None)
    await db["dealer_organizations"].update_one(q, {"$set": data})
    dealer = await db["dealer_organizations"].find_one(q)
    return serialize_doc(dealer)


@router.post("/dealers/{dealer_id}/upload-doc")
async def admin_upload_dealer_doc(
    dealer_id: str,
    file: UploadFile = File(...),
    doc_type: str = "logo",
    admin=Depends(require_admin),
):
    """Admin uploads a missing doc (logo, passport, ID, CAC) for a dealer before approval."""
    try:
        content = await file.read()
        content_type = file.content_type or ""
        is_pdf = "pdf" in content_type or file.filename.lower().endswith(".pdf")
        resource_type = "raw" if is_pdf else "image"
        result = cloudinary.uploader.upload(
            content, resource_type=resource_type,
            folder=f"carstrims/admin-uploads/{doc_type}",
            use_filename=True,
        )
        url = result["secure_url"]
        q = {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
        field_map = {
            "logo": "logo", "passport": "passportPhoto",
            "id": "idCardUrl", "cac": "cacUrl",
        }
        field = field_map.get(doc_type, doc_type)
        await db["dealer_organizations"].update_one(q, {"$set": {field: url, "updatedAt": datetime.utcnow()}})
        return {"url": url, "field": field, "message": f"{doc_type} uploaded and attached"}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Upload failed: {str(e)}")
