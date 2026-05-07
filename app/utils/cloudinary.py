import cloudinary
import cloudinary.uploader
from app.config.settings import settings
from fastapi import HTTPException, UploadFile
import os

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
    secure=True,
)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024   # 10MB
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB


async def upload_image(
    file: UploadFile,
    folder: str,
    public_id: str = None,
) -> dict:
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}",
        )

    contents = await file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="Image too large. Max 10MB.")

    try:
        result = cloudinary.uploader.upload(
            contents,
            folder=f"car-dealer-app/{folder}",
            public_id=public_id,
            overwrite=True,
            transformation=[
                {"width": 1200, "height": 900, "crop": "limit"},
                {"quality": "auto"},
                {"fetch_format": "auto"},
            ],
        )
        return {
            "url": result["secure_url"],
            "public_id": result["public_id"],
            "width": result.get("width"),
            "height": result.get("height"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


async def upload_video(
    file: UploadFile,
    folder: str,
    public_id: str = None,
) -> dict:
    if file.content_type not in ALLOWED_VIDEO_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Invalid video type. Allowed: mp4, mov, webm",
        )

    contents = await file.read()
    if len(contents) > MAX_VIDEO_SIZE:
        raise HTTPException(status_code=400, detail="Video too large. Max 100MB.")

    try:
        result = cloudinary.uploader.upload(
            contents,
            resource_type="video",
            folder=f"car-dealer-app/{folder}",
            public_id=public_id,
            overwrite=True,
            transformation=[
                {"duration": "30", "crop": "limit"},
                {"quality": "auto"},
            ],
        )
        return {
            "url": result["secure_url"],
            "public_id": result["public_id"],
            "duration": result.get("duration"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Video upload failed: {str(e)}")


async def upload_document(
    file: UploadFile,
    folder: str,
    public_id: str = None,
) -> dict:
    allowed = {"image/jpeg", "image/png", "application/pdf"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Allowed: JPG, PNG, PDF")

    contents = await file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Max 10MB.")

    resource_type = "raw" if file.content_type == "application/pdf" else "image"

    try:
        result = cloudinary.uploader.upload(
            contents,
            resource_type=resource_type,
            folder=f"car-dealer-app/{folder}",
            public_id=public_id,
            overwrite=True,
        )
        return {
            "url": result["secure_url"],
            "public_id": result["public_id"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document upload failed: {str(e)}")


def delete_file(public_id: str, resource_type: str = "image") -> bool:
    try:
        cloudinary.uploader.destroy(public_id, resource_type=resource_type)
        return True
    except Exception:
        return False
