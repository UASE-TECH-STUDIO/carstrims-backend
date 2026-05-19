from fastapi import APIRouter, Depends, UploadFile, File, Form, Body
from typing import Optional
from app.auth.dependencies import get_current_user, get_current_dealer
from app.utils.cloudinary import upload_image, upload_video, upload_document, delete_file
from app.database.connection import get_db
from app.modules.dealers.service import get_dealer_by_user_id, serialize_doc
from bson import ObjectId
from datetime import datetime
import uuid

router = APIRouter(prefix="/api/v1/upload", tags=["Uploads"])


# ── TEMP UPLOAD (no dealer profile required — used during setup) ──────────────
# Used for logo, passport, ID card BEFORE the dealer profile exists.
# Just uploads to Cloudinary and returns the URL. No DB writes.

@router.post("/temp/image")
async def temp_upload_image(
    file: UploadFile = File(...),
    folder: str = Form(default="temp"),
    current_user: dict = Depends(get_current_user),
):
    """Upload any image during setup — no dealer profile required."""
    uid = str(current_user["_id"])
    result = await upload_image(
        file,
        folder=f"setup/{folder}/{uid}",
        public_id=f"{folder}-{uid}-{uuid.uuid4().hex[:8]}",
    )
    return {"url": result["url"], "secure_url": result["url"]}


@router.post("/temp/document")
async def temp_upload_document(
    file: UploadFile = File(...),
    folder: str = Form(default="documents"),
    current_user: dict = Depends(get_current_user),
):
    """Upload any document during setup — no dealer profile required."""
    uid = str(current_user["_id"])
    result = await upload_document(
        file,
        folder=f"setup/{folder}/{uid}",
        public_id=f"doc-{uid}-{uuid.uuid4().hex[:8]}",
    )
    return {"url": result["url"], "secure_url": result["url"]}


# ── CAR IMAGES ────────────────────────────────────────────────

@router.post("/car/{car_id}/images")
async def upload_car_images(
    car_id: str,
    files: list[UploadFile] = File(...),
    current_user: dict = Depends(get_current_dealer),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    car = await db["car_listings"].find_one({
        "carId": car_id, "dealerId": dealer["_id"],
    })
    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Car not found")

    current_images = car.get("images", [])
    if len(current_images) + len(files) > 10:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Max 10 images. Currently have {len(current_images)}.")

    uploaded_urls = []
    for file in files:
        result = await upload_image(
            file,
            folder=f"cars/{car_id}/images",
            public_id=f"{car_id}-{uuid.uuid4().hex[:8]}",
        )
        uploaded_urls.append(result["url"])

    new_images = current_images + uploaded_urls
    await db["car_listings"].update_one(
        {"carId": car_id},
        {"$set": {"images": new_images, "updatedAt": datetime.utcnow()}},
    )

    return {"message": f"{len(uploaded_urls)} image(s) uploaded", "images": new_images}


@router.delete("/car/{car_id}/images")
async def delete_car_image(
    car_id: str,
    data: dict = Body(...),
    current_user: dict = Depends(get_current_dealer),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    image_url = data.get("image_url", "")

    car = await db["car_listings"].find_one({
        "carId": car_id, "dealerId": dealer["_id"],
    })
    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Car not found")

    updated_images = [img for img in car.get("images", []) if img != image_url]
    await db["car_listings"].update_one(
        {"carId": car_id},
        {"$set": {"images": updated_images, "updatedAt": datetime.utcnow()}},
    )

    return {"message": "Image removed", "images": updated_images}


# ── CAR VIDEO ─────────────────────────────────────────────────

@router.post("/car/{car_id}/video")
async def upload_car_video(
    car_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_dealer),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    car = await db["car_listings"].find_one({
        "carId": car_id, "dealerId": dealer["_id"],
    })
    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Car not found")

    result = await upload_video(
        file,
        folder=f"cars/{car_id}",
        public_id=f"{car_id}-video",
    )

    await db["car_listings"].update_one(
        {"carId": car_id},
        {"$set": {"video": result["url"], "updatedAt": datetime.utcnow()}},
    )

    return {"message": "Video uploaded", "video": result["url"]}


# ── DEALER LOGO (requires approved dealer) ────────────────────

@router.post("/dealer/logo")
async def upload_dealer_logo(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_dealer),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    result = await upload_image(
        file,
        folder=f"dealers/{dealer['_id']}/logo",
        public_id=f"logo-{dealer['_id']}",
    )

    await db["dealer_organizations"].update_one(
        {"_id": ObjectId(dealer["_id"])},
        {"$set": {"logo": result["url"], "updatedAt": datetime.utcnow()}},
    )

    return {"message": "Logo uploaded", "logo": result["url"]}


@router.post("/dealer/banner")
async def upload_dealer_banner(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_dealer),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    result = await upload_image(
        file,
        folder=f"dealers/{dealer['_id']}/banner",
        public_id=f"banner-{dealer['_id']}",
    )

    await db["dealer_organizations"].update_one(
        {"_id": ObjectId(dealer["_id"])},
        {"$set": {"banner": result["url"], "updatedAt": datetime.utcnow()}},
    )

    return {"message": "Banner uploaded", "banner": result["url"]}


# ── PROFILE PICTURE ───────────────────────────────────────────

@router.post("/profile/picture")
async def upload_profile_picture(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    user_id = str(current_user["_id"])

    result = await upload_image(
        file,
        folder=f"users/{user_id}",
        public_id=f"profile-{user_id}",
    )

    await db["users"].update_one(
        {"_id": current_user["_id"]},
        {"$set": {"profilePicture": result["url"], "updatedAt": datetime.utcnow()}},
    )

    if current_user.get("role") == "DEALER_STAFF":
        await db["staff_accounts"].update_one(
            {"userId": user_id},
            {"$set": {"profilePicture": result["url"], "updatedAt": datetime.utcnow()}},
        )

    return {"message": "Profile picture uploaded", "profilePicture": result["url"]}


# ── MOVEMENT ID CARD ──────────────────────────────────────────

@router.post("/movement/id-card")
async def upload_id_card(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_dealer),
):
    result = await upload_document(
        file,
        folder="movement-ids",
        public_id=f"id-{uuid.uuid4().hex[:12]}",
    )
    return {"message": "ID card uploaded", "idCardUrl": result["url"]}


# ── GENERIC DOCUMENT ──────────────────────────────────────────

@router.post("/document")
async def upload_generic_document(
    file: UploadFile = File(...),
    folder: str = Form(default="documents"),
    current_user: dict = Depends(get_current_user),
):
    result = await upload_document(
        file,
        folder=folder,
        public_id=f"doc-{uuid.uuid4().hex[:12]}",
    )
    return {"message": "Document uploaded", "url": result["url"]}


# ── DEALER SIGNATURE (for invoices, receipts, reports) ────────────────────────
@router.post("/dealer/signature")
async def upload_dealer_signature(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_dealer),
):
    """Upload dealer signature image for use on all generated documents."""
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))

    result = await upload_image(
        file,
        folder=f"dealers/{dealer['_id']}/signature",
        public_id=f"signature-{dealer['_id']}",
    )

    await db["dealer_organizations"].update_one(
        {"_id": ObjectId(dealer["_id"])},
        {"$set": {"signature": result["url"], "updatedAt": datetime.utcnow()}},
    )

    return {"message": "Signature uploaded", "signature": result["url"]}
