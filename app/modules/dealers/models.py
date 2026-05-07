from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class DealerStatus(str, Enum):
    REGISTERED = "registered"
    SETUP_PENDING = "setup_pending"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SUSPENDED = "suspended"
    REJECTED = "rejected"
    DELETED = "deleted"


class DealerBase(BaseModel):
    companyName: str
    ownerName: str
    email: EmailStr
    phone: str
    whatsapp: Optional[str] = None
    address: str
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    logo: Optional[str] = None
    banner: Optional[str] = None
    description: Optional[str] = None


class DealerCreate(DealerBase):
    userId: str


class DealerInDB(DealerBase):
    id: Optional[str] = Field(None, alias="_id")
    userId: str
    status: DealerStatus = DealerStatus.REGISTERED
    qrCode: Optional[str] = None
    subscriptionPlan: str = "free"
    totalCarsListed: int = 0
    totalCarsSold: int = 0
    totalRevenue: float = 0.0
    warningNote: Optional[str] = None
    approvedAt: Optional[datetime] = None
    approvedBy: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


class DealerResponse(DealerBase):
    id: str
    userId: str
    status: DealerStatus
    qrCode: Optional[str] = None
    totalCarsListed: int
    totalCarsSold: int
    totalRevenue: float
    createdAt: datetime

    class Config:
        populate_by_name = True
