from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class StaffPermission(str, Enum):
    VIEW_INVENTORY = "view_inventory"
    ADD_CARS = "add_cars"
    EDIT_CARS = "edit_cars"
    DELETE_CARS = "delete_cars"
    VIEW_SALES = "view_sales"
    RECORD_SALES = "record_sales"
    VIEW_STAFF = "view_staff"
    CREATE_STAFF = "create_staff"
    EDIT_STAFF = "edit_staff"
    SUSPEND_STAFF = "suspend_staff"
    VIEW_PARTNERS = "view_partners"
    MANAGE_PARTNERS = "manage_partners"
    VIEW_CCTV = "view_cctv"
    VIEW_MOVEMENTS = "view_movements"
    MANAGE_MOVEMENTS = "manage_movements"
    VIEW_REPORTS = "view_reports"


class StaffStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class StaffBase(BaseModel):
    fullName: str
    email: EmailStr
    phone: str
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    position: str
    staffId: Optional[str] = None
    profilePicture: Optional[str] = None


class StaffCreate(StaffBase):
    dealerId: str
    userId: str
    permissions: List[StaffPermission] = []


class StaffInDB(StaffBase):
    id: Optional[str] = Field(None, alias="_id")
    dealerId: str
    userId: str
    permissions: List[StaffPermission] = []
    status: StaffStatus = StaffStatus.ACTIVE
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)
    lastActive: Optional[datetime] = None

    class Config:
        populate_by_name = True


class StaffResponse(StaffBase):
    id: str
    dealerId: str
    userId: str
    permissions: List[StaffPermission]
    status: StaffStatus
    createdAt: datetime
    lastActive: Optional[datetime] = None

    class Config:
        populate_by_name = True
