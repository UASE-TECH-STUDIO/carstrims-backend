from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc
import random
import string


def generate_camera_id():
    return "CAM-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


async def add_camera(dealer_id: str, data: dict) -> dict:
    db = get_db()

    existing = await db["cctv_streams"].find_one({
        "dealerId": dealer_id,
        "streamUrl": data.get("streamUrl"),
    })
    if existing:
        raise HTTPException(status_code=400, detail="Camera with this stream URL already exists")

    camera_doc = {
        "cameraId": generate_camera_id(),
        "dealerId": dealer_id,
        "cameraName": data.get("cameraName"),
        "cameraLocation": data.get("cameraLocation"),
        "streamUrl": data.get("streamUrl"),
        "streamType": data.get("streamType", "rtsp"),
        "provider": data.get("provider"),
        "status": "offline",
        "lastOnline": None,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    result = await db["cctv_streams"].insert_one(camera_doc)
    camera_doc["_id"] = result.inserted_id
    return serialize_doc(camera_doc)


async def get_cameras(dealer_id: str) -> dict:
    db = get_db()
    cameras = await db["cctv_streams"].find(
        {"dealerId": dealer_id}
    ).sort("createdAt", -1).to_list(50)

    total = len(cameras)
    online = sum(1 for c in cameras if c.get("status") == "online")

    return {
        "total": total,
        "online": online,
        "offline": total - online,
        "cameras": [serialize_doc(c) for c in cameras],
    }


async def update_camera(camera_id: str, dealer_id: str, data: dict) -> dict:
    db = get_db()

    if ObjectId.is_valid(camera_id):
        query = {"_id": ObjectId(camera_id), "dealerId": dealer_id}
    else:
        query = {"cameraId": camera_id, "dealerId": dealer_id}

    camera = await db["cctv_streams"].find_one(query)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    data.pop("_id", None)
    data.pop("dealerId", None)
    data["updatedAt"] = datetime.utcnow()

    await db["cctv_streams"].update_one({"_id": camera["_id"]}, {"$set": data})

    updated = await db["cctv_streams"].find_one({"_id": camera["_id"]})
    return serialize_doc(updated)


async def delete_camera(camera_id: str, dealer_id: str) -> dict:
    db = get_db()

    if ObjectId.is_valid(camera_id):
        query = {"_id": ObjectId(camera_id), "dealerId": dealer_id}
    else:
        query = {"cameraId": camera_id, "dealerId": dealer_id}

    camera = await db["cctv_streams"].find_one(query)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    await db["cctv_streams"].delete_one({"_id": camera["_id"]})
    return {"message": "Camera removed successfully"}


async def ping_camera(camera_id: str, dealer_id: str) -> dict:
    db = get_db()

    if ObjectId.is_valid(camera_id):
        query = {"_id": ObjectId(camera_id), "dealerId": dealer_id}
    else:
        query = {"cameraId": camera_id, "dealerId": dealer_id}

    camera = await db["cctv_streams"].find_one(query)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    # Mark as online when pinged (real implementation would check stream)
    await db["cctv_streams"].update_one(
        {"_id": camera["_id"]},
        {"$set": {
            "status": "online",
            "lastOnline": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
        }},
    )

    return {"message": "Camera is online", "cameraId": camera.get("cameraId")}
