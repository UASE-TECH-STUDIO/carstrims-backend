from pydantic import BaseModel, EmailStr
from typing import Optional
from enum import Enum


class UserRole(str, Enum):
    DEALER_ADMIN = "DEALER_ADMIN"
    PARTNER_USER = "PARTNER_USER"
    PUBLIC_USER = "PUBLIC_USER"


class RegisterRequest(BaseModel):
    fullName: str
    username: str
    email: EmailStr
    password: str
    phone: str
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    role: UserRole   # ✅ keep enum


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    accessToken: str
    refreshToken: str
    userId: str
    fullName: str
    email: str
    role: str
    dealerId: Optional[str] = None


class RefreshRequest(BaseModel):
    refreshToken: str


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr