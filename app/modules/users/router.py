from fastapi import APIRouter, Depends, Query, Body, UploadFile, File
from typing import Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_user
from app.modules.dealers.service import serialize_doc
from app.modules.users.user_service import (
    get_favorites, add_favorite, remove_favorite,
    toggle_like, get_user_likes,
    create_special_request, get_user_requests, respond_to_request,
    create_appointment, get_user_appointments,
    update_user_profile,
)
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime
import cloudinary, cloudinary.uploader
from app.config.settings import settings

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
)


class ProfileUpdate(BaseModel):
    fullName: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    bio: Optional[str] = None
    instagram: Optional[str] = None
    facebook: Optional[str] = None
    twitter: Optional[str] = None
    tiktok: Optional[str] = None
    website: Optional[str] = None
    showPhone: Optional[bool] = None
    showWhatsapp: Optional[bool] = None
    showEmail: Optional[bool] = None


router = APIRouter(prefix="/api/v1/users", tags=["Users"])


# ── ME / PROFILE ─────────────────────────────────────────────────────────────

@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    s = serialize_doc(current_user)
    s.pop("passwordHash", None)
    return s


@router.patch("/me")
async def update_me(data: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    return await update_user_profile(str(current_user["_id"]), data.model_dump(exclude_none=True))


# ── AVATAR UPLOAD ────────────────────────────────────────────────────────────

@router.post("/upload/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    try:
        content = await file.read()
        result = cloudinary.uploader.upload(
            content,
            resource_type="image",
            folder="carstrims/avatars",
            public_id=f"user-{str(current_user['_id'])}",
            overwrite=True,
            transformation=[{"width": 400, "height": 400, "crop": "fill", "gravity": "face"}],
        )
        avatar_url = result["secure_url"]
        db = get_db()
        await db["users"].update_one(
            {"_id": ObjectId(str(current_user["_id"]))},
            {"$set": {"avatar": avatar_url, "updatedAt": datetime.utcnow()}}
        )
        return {"url": avatar_url, "message": "Avatar updated"}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Upload failed: {str(e)}")


# ── FAVORITES ────────────────────────────────────────────────────────────────
# These endpoints read from the SAME "favorites" collection
# that POST /api/v1/public/cars/{id}/favorite writes to.
# This is what makes the feed's Save button show up in the dashboard.

@router.get("/favorites")
async def get_my_favorites(current_user: dict = Depends(get_current_user)):
    return await get_favorites(str(current_user["_id"]))


@router.post("/favorites/{car_id}")
async def save_car(car_id: str, current_user: dict = Depends(get_current_user)):
    return await add_favorite(str(current_user["_id"]), car_id)


@router.delete("/favorites/{car_id}")
async def unsave_car(car_id: str, current_user: dict = Depends(get_current_user)):
    return await remove_favorite(str(current_user["_id"]), car_id)


# ── LIKES ────────────────────────────────────────────────────────────────────

@router.get("/likes")
async def get_my_likes(current_user: dict = Depends(get_current_user)):
    return await get_user_likes(str(current_user["_id"]))


# ── REQUESTS ─────────────────────────────────────────────────────────────────

@router.get("/requests")
async def get_my_requests(current_user: dict = Depends(get_current_user)):
    return await get_user_requests(str(current_user["_id"]))


@router.post("/requests")
async def create_request(data: dict = Body(...), current_user: dict = Depends(get_current_user)):
    return await create_special_request(str(current_user["_id"]), data)


@router.post("/requests/{request_id}/accept")
async def accept_request(request_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    await db["special_requests"].update_one(
        {"requestId": request_id, "userId": str(current_user["_id"])},
        {"$set": {"status": "accepted", "updatedAt": datetime.utcnow()}},
    )
    return {"message": "Request accepted"}


@router.post("/requests/{request_id}/reject")
async def reject_request(request_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    await db["special_requests"].update_one(
        {"requestId": request_id, "userId": str(current_user["_id"])},
        {"$set": {"status": "rejected_by_user", "updatedAt": datetime.utcnow()}},
    )
    return {"message": "Rejected"}


# ── APPOINTMENTS ─────────────────────────────────────────────────────────────

@router.get("/appointments")
async def get_my_appointments(current_user: dict = Depends(get_current_user)):
    return await get_user_appointments(str(current_user["_id"]))


@router.post("/appointments")
async def book_appointment(data: dict = Body(...), current_user: dict = Depends(get_current_user)):
    return await create_appointment(str(current_user["_id"]), data)
