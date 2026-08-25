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
    targetUserIds: Optional[List[str]] = None
    documentUrl: Optional[str] = None
    documentName: Optional[str] = None
    documentType: Optional[str] = None
    sendEmail: bool = False


router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


#  STATS
@router.get("/stats")
async def get_stats(admin=Depends(require_admin)):
    db = get_db()
    total_dealers     = await db["dealer_organizations"].count_documents({})
    active_dealers    = await db["dealer_organizations"].count_documents({"status": "approved"})
    pending_dealers   = await db["dealer_organizations"].count_documents({"status": "awaiting_approval"})
    suspended_dealers = await db["dealer_organizations"].count_documents({"status": "suspended"})

    total_users    = await db["users"].count_documents({})
    buyers_only    = await db["users"].count_documents({"role": "PUBLIC_USER"})
    partners_only  = await db["users"].count_documents({"role": "PARTNER_USER"})
    staff_only     = await db["users"].count_documents({"role": "DEALER_STAFF"})
    dealer_admins  = await db["users"].count_documents({"role": "DEALER_ADMIN"})

    total_cars = await db["car_listings"].count_documents({})
    total_sold = await db["car_listings"].count_documents({"status": "sold"})

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


#  DEALERS
@router.get("/dealers")
async def list_dealers(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    skip: int = Query(0), limit: int = Query(20),
    admin=Depends(require_admin),
):
    db = get_db()
    query = {}
    if status and status != "all":
        query["status"] = status
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
        s["carCount"]   = await db["car_listings"].count_documents({"dealerId": str(d["_id"])})
        s["soldCount"]  = await db["car_listings"].count_documents({"dealerId": str(d["_id"]), "status": "sold"})
        if d.get("userId"):
            user_doc = await db["users"].find_one({"_id": ObjectId(d["userId"])}) if ObjectId.is_valid(str(d["userId"])) else None
            if not user_doc:
                user_doc = await db["users"].find_one({"userId": str(d["userId"])})
            if user_doc:
                for field in ["passportPhoto", "idCardUrl", "cacUrl", "isRegisteredBusiness", "profilePicture", "avatar"]:
                    if not s.get(field) and user_doc.get(field):
                        s[field] = user_doc[field]
                s["ownerEmail"]  = user_doc.get("email")
                s["ownerPhone"]  = user_doc.get("phone")
                s["ownerStatus"] = user_doc.get("status")
        enriched.append(s)
    return {"total": total, "dealers": enriched}


@router.get("/dealers/{dealer_id}/setup")
async def get_dealer_setup(dealer_id: str, admin=Depends(require_admin)):
    db = get_db()
    dealer = None
    if ObjectId.is_valid(dealer_id):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(dealer_id)})
    if not dealer:
        dealer = await db["dealer_organizations"].find_one({"dealerId": dealer_id})
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")

    result = serialize_doc(dealer)
    result["staffCount"] = await db["staff_accounts"].count_documents({"dealerId": str(dealer["_id"])})
    result["carCount"]   = await db["car_listings"].count_documents({"dealerId": str(dealer["_id"])})
    result["soldCount"]  = await db["car_listings"].count_documents({"dealerId": str(dealer["_id"]), "status": "sold"})

    owner = None
    if dealer.get("userId"):
        uid = str(dealer["userId"])
        if ObjectId.is_valid(uid):
            owner = await db["users"].find_one({"_id": ObjectId(uid)})
        if not owner:
            owner = await db["users"].find_one({"userId": uid})
    if owner:
        result["ownerUser"] = {
            "fullName": owner.get("fullName"),
            "email": owner.get("email"),
            "phone": owner.get("phone"),
            "status": owner.get("status"),
            "_id": str(owner["_id"]),
        }
        for field in ["passportPhoto", "idCardUrl", "cacUrl", "isRegisteredBusiness"]:
            if not result.get(field) and owner.get(field):
                result[field] = owner[field]

    cars = await db["car_listings"].find({"dealerId": str(dealer["_id"])}).sort("createdAt", -1).limit(10).to_list(10)
    result["recentCars"] = [serialize_doc(c) for c in cars]
    return result


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
        "title": "Dealership Approved",
        "message": "Your dealership has been approved. You now have full access to your dashboard.",
        "isRead": False, "createdAt": datetime.utcnow(),
    })

    # Fire push notification
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(
            dealer["userId"],
            "Dealership Approved",
            "Your dealership has been approved. You now have full access to your dashboard.",
            "/dashboard",
        ))
    except Exception:
        pass

    # Send real email + WhatsApp notification
    try:
        user_obj = await db["users"].find_one({"_id": ObjectId(dealer["userId"])})
        if user_obj:
            from app.services.notifications import notify_dealer_approved
            import asyncio
            asyncio.create_task(notify_dealer_approved(dealer, user_obj))
    except Exception:
        pass

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

    # Fire push notification
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(dealer["userId"], "Application Rejected", reason, "/dashboard"))
    except Exception:
        pass

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
        "title": "Account Suspended", "message": note,
        "isRead": False, "createdAt": datetime.utcnow(),
    })

    # Fire push notification
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(dealer["userId"], "Account Suspended", note, "/dashboard"))
    except Exception:
        pass

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
        "title": "Account Warning", "message": note,
        "isRead": False, "createdAt": datetime.utcnow(),
    })

    # Fire push notification
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(dealer["userId"], "Account Warning", note, "/dashboard"))
    except Exception:
        pass

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


#  CARS (platform-wide, for the super admin "Cars Listed" page)
@router.get("/cars")
async def list_all_cars(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    dealer_id: Optional[str] = Query(None),
    skip: int = Query(0), limit: int = Query(20),
    admin=Depends(require_admin),
):
    db = get_db()
    query: dict = {}
    if status and status != "all":
        query["status"] = status
    if dealer_id:
        query["dealerId"] = dealer_id
    if search:
        query["$or"] = [
            {"brand": {"$regex": search, "$options": "i"}},
            {"model": {"$regex": search, "$options": "i"}},
            {"carId": {"$regex": search, "$options": "i"}},
        ]
    total = await db["car_listings"].count_documents(query)
    cars = await db["car_listings"].find(query).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)

    # Batch dealer lookup (same pattern as the public feed fix) instead
    # of one query per car.
    dealer_ids = list({c["dealerId"] for c in cars if ObjectId.is_valid(c.get("dealerId", ""))})
    dealers_by_id = {}
    if dealer_ids:
        docs = await db["dealer_organizations"].find({"_id": {"$in": [ObjectId(d) for d in dealer_ids]}}).to_list(len(dealer_ids))
        dealers_by_id = {str(d["_id"]): d for d in docs}

    enriched = []
    for c in cars:
        s = serialize_doc(c)
        dealer = dealers_by_id.get(c.get("dealerId"))
        s["dealerName"] = dealer.get("companyName") if dealer else None
        enriched.append(s)
    return {"total": total, "cars": enriched}


async def _get_car_and_dealer(car_id: str, db):
    q = {"_id": ObjectId(car_id)} if ObjectId.is_valid(car_id) else {"carId": car_id}
    car = await db["car_listings"].find_one(q)
    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Car not found")
    dealer = None
    if ObjectId.is_valid(car.get("dealerId", "")):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(car["dealerId"])})
    return car, dealer, q


async def _notify_dealer_about_car(dealer, title: str, message: str):
    """Same notification + best-effort push pattern already used for
    suspend_dealer/warn_dealer above - kept as a shared helper here
    since every car moderation action below needs the identical
    steps, just with a different title/message."""
    if not dealer or not dealer.get("userId"):
        return
    db = get_db()
    await db["notifications"].insert_one({
        "receiverId": dealer["userId"], "type": "general",
        "title": title, "message": message,
        "isRead": False, "createdAt": datetime.utcnow(),
    })
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(dealer["userId"], title, message, "/dashboard"))
    except Exception:
        pass


@router.post("/cars/{car_id}/hide")
async def hide_car(car_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    """Removes a listing from the public feed without deleting it -
    the dealer keeps it in their own inventory and can see exactly
    why it was taken down, ready to be re-published once addressed."""
    db = get_db()
    car, dealer, q = await _get_car_and_dealer(car_id, db)
    note = data.get("note", "This listing has been hidden from the public feed pending review.")
    await db["car_listings"].update_one(q, {"$set": {"adminHidden": True, "adminHiddenNote": note, "updatedAt": datetime.utcnow()}})
    await _notify_dealer_about_car(dealer, "Vehicle Listing Hidden", f"{car.get('brand','')} {car.get('model','')}: {note}")
    return {"message": "Car hidden"}


@router.post("/cars/{car_id}/unhide")
async def unhide_car(car_id: str, admin=Depends(require_admin)):
    """Re-publishes a previously hidden listing back to the public
    feed."""
    db = get_db()
    car, dealer, q = await _get_car_and_dealer(car_id, db)
    await db["car_listings"].update_one(q, {"$set": {"adminHidden": False, "updatedAt": datetime.utcnow()}, "$unset": {"adminHiddenNote": ""}})
    await _notify_dealer_about_car(dealer, "Vehicle Listing Re-published", f"{car.get('brand','')} {car.get('model','')} is visible on the public feed again.")
    return {"message": "Car unhidden"}


@router.post("/cars/{car_id}/mute")
async def mute_car(car_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    """Disables further comments on a specific listing - the car
    stays visible and purchasable, only new comments are blocked.
    Less severe than hiding: for a listing whose discussion needs
    moderating, not the listing itself."""
    db = get_db()
    car, dealer, q = await _get_car_and_dealer(car_id, db)
    note = data.get("note", "Comments have been disabled on this listing.")
    await db["car_listings"].update_one(q, {"$set": {"adminMuted": True, "adminMutedNote": note, "updatedAt": datetime.utcnow()}})
    await _notify_dealer_about_car(dealer, "Comments Disabled", f"{car.get('brand','')} {car.get('model','')}: {note}")
    return {"message": "Car muted"}


@router.post("/cars/{car_id}/unmute")
async def unmute_car(car_id: str, admin=Depends(require_admin)):
    db = get_db()
    car, dealer, q = await _get_car_and_dealer(car_id, db)
    await db["car_listings"].update_one(q, {"$set": {"adminMuted": False, "updatedAt": datetime.utcnow()}, "$unset": {"adminMutedNote": ""}})
    await _notify_dealer_about_car(dealer, "Comments Re-enabled", f"Comments are open again on {car.get('brand','')} {car.get('model','')}.")
    return {"message": "Car unmuted"}


#  USERS
@router.get("/users")
async def list_users(
    role: Optional[str] = Query(None),
    skip: int = Query(0), limit: int = Query(20),
    search: Optional[str] = Query(None),
    admin=Depends(require_admin),
):
    db = get_db()
    query: dict = {}
    if role and role != "all":
        query["role"] = role
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


@router.get("/users/{user_id}/profile")
async def get_user_full_profile(user_id: str, admin=Depends(require_admin)):
    db = get_db()
    user = None
    if ObjectId.is_valid(user_id):
        user = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not user:
        user = await db["users"].find_one({"userId": user_id})
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")

    s = serialize_doc(user)
    s.pop("passwordHash", None)

    dealer = None
    if user.get("role") in ("DEALER_ADMIN", "DEALER_STAFF"):
        if user.get("role") == "DEALER_ADMIN":
            dealer = await db["dealer_organizations"].find_one({"userId": str(user["_id"])})
        else:
            staff = await db["staff_accounts"].find_one({"userId": str(user["_id"])})
            if staff:
                dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(staff["dealerId"])}) if ObjectId.is_valid(str(staff.get("dealerId", ""))) else None
        if dealer:
            ds = serialize_doc(dealer)
            for field in ["passportPhoto", "idCardUrl", "cacUrl", "isRegisteredBusiness"]:
                if not ds.get(field) and s.get(field):
                    ds[field] = s[field]
            s["dealer"] = ds
            cars = await db["car_listings"].find({"dealerId": str(dealer["_id"])}).sort("createdAt", -1).limit(20).to_list(20)
            s["recentCars"] = [serialize_doc(c) for c in cars]

    appts = await db["appointments"].find({"userId": str(user["_id"])}).sort("createdAt", -1).limit(10).to_list(10)
    s["appointments"] = [serialize_doc(a) for a in appts]

    requests = await db["special_requests"].find({"userId": str(user["_id"])}).sort("createdAt", -1).limit(10).to_list(10)
    s["vehicleRequests"] = [serialize_doc(r) for r in requests]

    return s


@router.patch("/users/{user_id}/profile")
async def update_user_profile_admin(user_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    db = get_db()
    data.pop("_id", None)
    data.pop("passwordHash", None)
    data["updatedAt"] = datetime.utcnow()
    q = {"_id": ObjectId(user_id)} if ObjectId.is_valid(user_id) else {"userId": user_id}
    await db["users"].update_one(q, {"$set": data})
    return {"message": "Profile updated"}


@router.post("/users/{user_id}/upload-doc")
async def admin_upload_user_doc(
    user_id: str,
    field: str = Query(...),
    folder: str = Query("documents"),
    file: UploadFile = File(...),
    admin=Depends(require_admin),
):
    db = get_db()
    contents = await file.read()
    result = cloudinary.uploader.upload(
        contents,
        folder=f"carstrims/{folder}",
        resource_type="auto",
    )
    url = result.get("secure_url")
    if not url:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Upload failed")

    q = {"_id": ObjectId(user_id)} if ObjectId.is_valid(user_id) else {"userId": user_id}
    await db["users"].update_one(q, {"$set": {field: url, "updatedAt": datetime.utcnow()}})

    if field in ("passportPhoto", "logo", "idCardUrl", "cacUrl"):
        user = await db["users"].find_one(q)
        if user:
            dealer = await db["dealer_organizations"].find_one({"userId": str(user["_id"])})
            if dealer:
                await db["dealer_organizations"].update_one(
                    {"_id": dealer["_id"]},
                    {"$set": {field: url, "updatedAt": datetime.utcnow()}}
                )

    return {"url": url, "field": field}


# Maps the short doc_type values the frontend sends to the actual field
# names stored on the dealer_organizations document.
_DEALER_DOC_TYPE_FIELDS = {
    "logo": "logo", "id": "idCardUrl", "cac": "cacUrl", "passport": "passportPhoto",
}


@router.post("/dealers/{dealer_id}/upload-doc")
async def admin_upload_dealer_doc(
    dealer_id: str,
    doc_type: str = Query(...),
    file: UploadFile = File(...),
    admin=Depends(require_admin),
):
    """
    This endpoint was called by the dealer detail page's document
    upload UI but never actually existed — every upload attempt there
    hit a genuine 404 from FastAPI's own routing, showing as a raw
    'not found' error. The equivalent action from the linked owner's
    user account page worked because it hits the separate, existing
    /users/{user_id}/upload-doc endpoint above.
    """
    field = _DEALER_DOC_TYPE_FIELDS.get(doc_type)
    if not field:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown doc_type: {doc_type}")

    db = get_db()
    q = {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
    dealer = await db["dealer_organizations"].find_one(q)
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")

    contents = await file.read()
    result = cloudinary.uploader.upload(contents, folder="carstrims/documents", resource_type="auto")
    url = result.get("secure_url")
    if not url:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Upload failed")

    await db["dealer_organizations"].update_one(
        {"_id": dealer["_id"]}, {"$set": {field: url, "updatedAt": datetime.utcnow()}}
    )

    # Cascade to the linked user account too, same as the reverse
    # direction already does, so both stay in sync regardless of which
    # page the upload happened from.
    if dealer.get("userId") and ObjectId.is_valid(dealer["userId"]):
        await db["users"].update_one(
            {"_id": ObjectId(dealer["userId"])},
            {"$set": {field: url, "updatedAt": datetime.utcnow()}}
        )

    return {"url": url, "field": field}


@router.delete("/dealers/{dealer_id}/remove-doc")
async def admin_remove_dealer_doc(
    dealer_id: str,
    doc_type: str = Query(...),
    admin=Depends(require_admin),
):
    """
    Clears an uploaded dealer document so admin can remove a wrong
    upload, or clear it to make way for a replacement (the upload UI
    only shows an empty upload slot when the field is unset - clearing
    it here is what lets a fresh upload happen in its place).

    Does not delete the file from Cloudinary itself - only clears the
    reference on the dealer/user record. Leaving the original file in
    storage is deliberate: safer than an irreversible delete if this
    was clicked by mistake, and Cloudinary storage cost for a handful
    of document images is negligible compared to the risk of losing a
    legitimate document permanently.
    """
    field = _DEALER_DOC_TYPE_FIELDS.get(doc_type)
    if not field:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unknown doc_type: {doc_type}")

    db = get_db()
    q = {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
    dealer = await db["dealer_organizations"].find_one(q)
    if not dealer:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Dealer not found")

    await db["dealer_organizations"].update_one(
        {"_id": dealer["_id"]}, {"$set": {field: None, "updatedAt": datetime.utcnow()}}
    )

    # Same cascade as upload - keep the linked user account in sync
    # regardless of which page the removal happened from.
    if dealer.get("userId") and ObjectId.is_valid(dealer["userId"]):
        await db["users"].update_one(
            {"_id": ObjectId(dealer["userId"])},
            {"$set": {field: None, "updatedAt": datetime.utcnow()}}
        )

    return {"field": field, "removed": True}


@router.post("/users/{user_id}/restrict-profile-field")
async def restrict_profile_field(user_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    db = get_db()
    field = data.get("field")
    reason = data.get("reason", "")
    q = {"_id": ObjectId(user_id)} if ObjectId.is_valid(user_id) else {"userId": user_id}
    await db["users"].update_one(q, {"$set": {f"restricted.{field}": reason, "updatedAt": datetime.utcnow()}})
    return {"message": f"Field {field} restricted"}


@router.post("/users/{user_id}/suspend")
async def suspend_user(user_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    db = get_db()
    reason = data.get("reason", "Your account has been suspended.")
    await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": {"status": "suspended", "updatedAt": datetime.utcnow()}})
    await db["notifications"].insert_one({
        "receiverId": user_id, "type": "general",
        "title": "Account Suspended", "message": reason,
        "isRead": False, "createdAt": datetime.utcnow(),
    })

    # Fire push notification
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(user_id, "Account Suspended", reason, "/dashboard"))
    except Exception:
        pass

    return {"message": "User suspended"}


@router.post("/users/{user_id}/unsuspend")
async def unsuspend_user(user_id: str, admin=Depends(require_admin)):
    db = get_db()
    await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": {"status": "active", "updatedAt": datetime.utcnow()}})
    await db["notifications"].insert_one({
        "receiverId": user_id, "type": "general",
        "title": "Account Reactivated",
        "message": "Your account has been reactivated. Welcome back!",
        "isRead": False, "createdAt": datetime.utcnow(),
    })

    # Fire push notification
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(user_id, "Account Reactivated", "Your account has been reactivated. Welcome back!", "/dashboard"))
    except Exception:
        pass

    return {"message": "User unsuspended"}


@router.post("/users/{user_id}/warn")
async def warn_user(user_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    db = get_db()
    reason = data.get("reason", "Please review your account activity.")
    await db["notifications"].insert_one({
        "receiverId": user_id, "type": "general",
        "title": "Account Warning", "message": reason,
        "isRead": False, "createdAt": datetime.utcnow(),
    })

    # Fire push notification
    try:
        import asyncio as _asyncio
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu
        _asyncio.create_task(_swpu(user_id, "Account Warning", reason, "/dashboard"))
    except Exception:
        pass

    return {"message": "Warning sent"}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, cascade: bool = Query(False), admin=Depends(require_admin)):
    """
    cascade=False (default): soft-deletes just the user account itself
    (status set to "deleted"), leaving all their content in place.

    cascade=True: also removes everything tied to that account —
    scoped carefully per role so this never touches anyone else's data:
      - Any role: their favorites, car likes, follows, comments, car
        requests, and notifications.
      - DEALER_ADMIN: their dealer organization record, every car they
        listed, all expense records and sale transactions under that
        dealer, and every staff account under that dealer (staff user
        accounts are soft-deleted, not hard-deleted, so nothing else
        referencing them breaks).
      - DEALER_STAFF: their staff_accounts entry.
    Message/conversation history is intentionally left untouched even
    with cascade=True, so deleting one person's account doesn't erase
    the other party's side of a conversation.
    """
    db = get_db()
    user = await db["users"].find_one({"_id": ObjectId(user_id)})
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")

    removed_counts: dict = {}

    if cascade:
        uid = str(user["_id"])
        role = user.get("role")

        r = await db["favorites"].delete_many({"userId": uid}); removed_counts["favorites"] = r.deleted_count
        r = await db["car_likes"].delete_many({"userId": uid}); removed_counts["car_likes"] = r.deleted_count
        r = await db["follows"].delete_many({"userId": uid}); removed_counts["follows"] = r.deleted_count
        r = await db["car_comments"].delete_many({"userId": uid}); removed_counts["comments"] = r.deleted_count
        r = await db["car_requests"].delete_many({"userId": uid}); removed_counts["car_requests"] = r.deleted_count
        r = await db["notifications"].delete_many({"receiverId": uid}); removed_counts["notifications"] = r.deleted_count

        if role == "DEALER_ADMIN":
            dealer = await db["dealer_organizations"].find_one({"userId": uid})
            if dealer:
                dealer_id = str(dealer["_id"])
                r = await db["car_listings"].delete_many({"dealerId": dealer_id}); removed_counts["cars"] = r.deleted_count
                r = await db["expense_records"].delete_many({"dealerId": dealer_id}); removed_counts["expenses"] = r.deleted_count
                r = await db["sale_transactions"].delete_many({"dealerId": dealer_id}); removed_counts["sales"] = r.deleted_count
                staff_docs = await db["staff_accounts"].find({"dealerId": dealer_id}).to_list(1000)
                for s in staff_docs:
                    if s.get("userId") and ObjectId.is_valid(s["userId"]):
                        await db["users"].update_one(
                            {"_id": ObjectId(s["userId"])},
                            {"$set": {"status": "deleted", "updatedAt": datetime.utcnow()}},
                        )
                r = await db["staff_accounts"].delete_many({"dealerId": dealer_id}); removed_counts["staff_accounts"] = r.deleted_count
                await db["dealer_organizations"].delete_one({"_id": dealer["_id"]})
                removed_counts["dealer_organization"] = 1

        elif role == "DEALER_STAFF":
            r = await db["staff_accounts"].delete_many({"userId": uid}); removed_counts["staff_accounts"] = r.deleted_count

        await db["admin_deletion_logs"].insert_one({
            "type": "user_cascade", "userId": uid, "userFullName": user.get("fullName"),
            "userRole": role, "deletedBy": str(admin["_id"]), "deletedAt": datetime.utcnow(),
            "removedCounts": removed_counts,
        })

    await db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": {"status": "deleted", "updatedAt": datetime.utcnow()}})
    return {"message": "User deleted", "cascade": cascade, "removedCounts": removed_counts}


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, data: dict = Body({}), admin=Depends(require_admin)):
    from app.auth.password import hash_password
    db = get_db()
    new_password = data.get("newPassword", "Reset@" + "".join(random.choices(string.digits + string.ascii_letters, k=8)))
    q = {"_id": ObjectId(user_id)} if ObjectId.is_valid(user_id) else {"userId": user_id}
    user = await db["users"].find_one(q)
    if not user:
        from fastapi import HTTPException
        raise HTTPException(404, "User not found")
    await db["users"].update_one(q, {"$set": {"passwordHash": hash_password(new_password), "updatedAt": datetime.utcnow()}})

    try:
        from app.services.notifications import notify_password_reset
        import asyncio
        asyncio.create_task(notify_password_reset(user, new_password, method="email"))
    except Exception:
        pass

    await db["notifications"].insert_one({
        "receiverId": str(user["_id"]),
        "type": "general",
        "title": "Password Reset by Admin",
        "message": f"Your password has been reset. New temporary password: {new_password}  Please change it after login.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })
    return {"message": "Password reset and user notified", "newPassword": new_password}


#  CAR MODERATION
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
    await db["car_comments"].delete_many({"carId": car.get("carId")})
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
    # BUG FIX: this was querying db["comments"], a collection that
    # doesn't actually exist — real comments live in db["car_comments"]
    # (see app/utils/comments_service.py). This meant admin comment
    # deletion always 404'd, silently, on every real comment.
    comment = await db["car_comments"].find_one({"commentId": comment_id})
    if not comment:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Comment not found")
    await db["car_comments"].delete_one({"commentId": comment_id})
    return {"message": "Comment deleted"}


#  BROADCAST
@router.post("/broadcast")
async def send_broadcast(data: BroadcastRequest, admin=Depends(require_admin)):
    db = get_db()
    admin_id = str(admin["_id"])
    now = datetime.utcnow()
    broadcast_id = "BCAST-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    system_user = await db["users"].find_one({"role": "SYSTEM_ADMIN"})
    system_id = str(system_user["_id"]) if system_user else admin_id

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
            "attachmentType": data.documentType,
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

    try:
        from app.services.notifications import send_broadcast_email
        import asyncio
        if data.sendEmail:
            recipient_users = await db["users"].find(
                {"_id": {"$in": [ObjectId(uid) for uid in user_ids if ObjectId.is_valid(uid)]}},
                {"email": 1, "fullName": 1}
            ).to_list(10000)
            asyncio.create_task(send_broadcast_email(
                recipient_users, data.title, data.message, data.title,
            ))
    except Exception:
        pass

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


#  UPLOAD
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
            "type": doc_type,
            "isImage": doc_type == "image",
            "isVideo": doc_type == "video",
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Upload failed: {str(e)}")


#  ANALYTICS
@router.get("/growth")
async def analytics_growth(admin=Depends(require_admin)):
    db = get_db()
    now = datetime.utcnow()
    months = []
    for i in range(5, -1, -1):
        month_offset = now.month - i
        year = now.year
        while month_offset <= 0:
            month_offset += 12
            year -= 1
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
        s = serialize_doc(d)
        s["rank"] = i + 1
        result.append(s)
    return result


@router.get("/activity")
async def activity_log(skip: int = Query(0), limit: int = Query(50), admin=Depends(require_admin)):
    db = get_db()
    docs = await db["notifications"].find({}).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    return {"activities": [serialize_doc(d) for d in docs]}


#  CREATE DEALER
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
        "fullName": data.get("fullName"),
        "username": data.get("username", email.split("@")[0]),
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