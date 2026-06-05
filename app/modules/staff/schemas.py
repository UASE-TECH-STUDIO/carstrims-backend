from pydantic import BaseModel, EmailStr
from typing import Optional, List


class StaffCreateRequest(BaseModel):
    fullName: str
    email: EmailStr
    phone: str
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    position: str
    password: Optional[str] = "Staff@1234"
    permissions: Optional[List[str]] = []
    username: Optional[str] = None  # auto-generated if not provided


class StaffUpdateRequest(BaseModel):
    fullName: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    position: Optional[str] = None


class StaffPermissionsRequest(BaseModel):
    permissions: List[str]
