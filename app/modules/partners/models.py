from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class PartnerStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class PartnerBase(BaseModel):
    fullName: str
    email: EmailStr
    phone: str
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    profilePicture: Optional[str] = None


class PartnerLinkCreate(BaseModel):
    userId: str
    dealerId: str


class PartnerLinkInDB(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    userId: str
    dealerId: str
    status: PartnerStatus = PartnerStatus.PENDING
    carIds: List[str] = []
    totalCarsAssigned: int = 0
    totalCarsSold: int = 0
    totalRevenue: float = 0.0
    totalPendingPayment: float = 0.0
    revenueSharePercent: Optional[float] = None
    requestedAt: datetime = Field(default_factory=datetime.utcnow)
    approvedAt: Optional[datetime] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


class PartnerLinkResponse(BaseModel):
    id: str
    userId: str
    dealerId: str
    status: PartnerStatus
    carIds: List[str]
    totalCarsAssigned: int
    totalCarsSold: int
    totalRevenue: float
    createdAt: datetime

    class Config:
        populate_by_name = True
