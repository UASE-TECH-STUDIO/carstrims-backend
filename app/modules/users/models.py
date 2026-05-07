from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    DEALER_ADMIN = "DEALER_ADMIN"
    DEALER_STAFF = "DEALER_STAFF"
    PARTNER_USER = "PARTNER_USER"
    PUBLIC_USER = "PUBLIC_USER"


class UserStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING = "pending"
    DELETED = "deleted"


class UserBase(BaseModel):
    fullName: str
    username: str
    email: EmailStr
    phone: str
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    country: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    role: UserRole = UserRole.PUBLIC_USER
    profilePicture: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserInDB(UserBase):
    id: Optional[str] = Field(None, alias="_id")
    passwordHash: str
    status: UserStatus = UserStatus.PENDING
    dealerId: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)
    lastLogin: Optional[datetime] = None
    isEmailVerified: bool = False

    class Config:
        populate_by_name = True


class UserResponse(UserBase):
    id: str
    status: UserStatus
    dealerId: Optional[str] = None
    createdAt: datetime
    lastLogin: Optional[datetime] = None

    class Config:
        populate_by_name = True
