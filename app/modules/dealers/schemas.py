from pydantic import BaseModel, EmailStr
from typing import Optional


class DealerSetupRequest(BaseModel):
    companyName: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    address: str
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = "Nigeria"
    description: Optional[str] = None


class DealerUpdateRequest(BaseModel):
    companyName: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    description: Optional[str] = None


class DealerActionRequest(BaseModel):
    reason: Optional[str] = None
