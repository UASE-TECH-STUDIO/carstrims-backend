from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class NotificationType(str, Enum):
    CAR_SOLD = "car_sold"
    CAR_ADDED = "car_added"
    CAR_MOVED = "car_moved"
    STAFF_ACTIVITY = "staff_activity"
    PARTNER_REQUEST = "partner_request"
    PAYMENT_RECEIVED = "payment_received"
    DEALER_APPROVED = "dealer_approved"
    DEALER_SUSPENDED = "dealer_suspended"
    CCTV_ALERT = "cctv_alert"
    EXPENSE_LOGGED = "expense_logged"
    GENERAL = "general"


class NotificationEvent(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    receiverId: str
    senderId: Optional[str] = None
    dealerId: Optional[str] = None
    type: NotificationType
    title: str
    message: str
    isRead: bool = False
    data: Optional[dict] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


class NotificationResponse(BaseModel):
    id: str
    receiverId: str
    type: NotificationType
    title: str
    message: str
    isRead: bool
    data: Optional[dict] = None
    createdAt: datetime

    class Config:
        populate_by_name = True
