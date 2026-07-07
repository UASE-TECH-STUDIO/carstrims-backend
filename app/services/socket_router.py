"""
Internal HTTP endpoints for socket operations.
Called from other FastAPI routes to push real-time events.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any
from app.services.socket_manager import (
    notify_user, broadcast_new_car, broadcast_car_sold,
    broadcast_to_room, get_connection_count, get_connected_users,
    notify_admins,
)

router = APIRouter(prefix="/api/v1/socket", tags=["socket"])


class NotifyRequest(BaseModel):
    userId: str
    type: str = "info"
    title: str
    message: str = ""
    data: Any = None


class BroadcastRequest(BaseModel):
    room: str = "public:feed"
    event: str
    data: Any = None


class CarBroadcastRequest(BaseModel):
    carId: str
    brand: str = ""
    model: str = ""
    year: int = 0
    sellingPrice: float = 0
    images: list = []
    status: str = "available"
    city: str = ""


@router.post("/notify")
async def push_notification(req: NotifyRequest):
    """Push notification to a specific user via socket."""
    await notify_user(req.userId, {
        "type":    req.type,
        "title":   req.title,
        "message": req.message,
        "data":    req.data,
    })
    return {"success": True, "userId": req.userId}


@router.post("/broadcast")
async def push_broadcast(req: BroadcastRequest):
    """Broadcast any event to any socket room."""
    await broadcast_to_room(req.room, req.event, req.data or {})
    return {"success": True, "room": req.room, "event": req.event}


@router.post("/broadcast/new-car")
async def push_new_car(req: CarBroadcastRequest):
    """Broadcast new car listing to public feed."""
    await broadcast_new_car(req.dict())
    return {"success": True}


@router.post("/broadcast/car-sold")
async def push_car_sold(car_id: str):
    """Broadcast car sold to public feed."""
    await broadcast_car_sold(car_id)
    return {"success": True}


@router.post("/notify-admins")
async def push_admin_notification(event: str, data: dict):
    """Send event to all system admins."""
    await notify_admins(event, data)
    return {"success": True}


@router.get("/stats")
async def socket_stats():
    """Get socket connection stats."""
    return {
        "connections": get_connection_count(),
        "users": list(get_connected_users().values()),
    }
