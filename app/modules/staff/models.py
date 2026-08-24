from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class StaffPermission(str, Enum):
    # Inventory
    VIEW_INVENTORY  = "view_inventory"
    ADD_CARS        = "add_cars"
    EDIT_CARS       = "edit_cars"
    DELETE_CARS     = "delete_cars"
    # Sales
    VIEW_SALES      = "view_sales"
    RECORD_SALES    = "record_sales"
    # Documents
    VIEW_INVOICES   = "view_invoices"
    GENERATE_INVOICES = "generate_invoices"
    EDIT_DOCUMENTS  = "edit_documents"
    # Staff management
    VIEW_STAFF      = "view_staff"
    CREATE_STAFF    = "create_staff"
    EDIT_STAFF      = "edit_staff"
    SUSPEND_STAFF   = "suspend_staff"
    # Partners
    VIEW_PARTNERS   = "view_partners"
    MANAGE_PARTNERS = "manage_partners"
    # CCTV
    VIEW_CCTV       = "view_cctv"
    # Movements
    VIEW_MOVEMENTS  = "view_movements"
    MANAGE_MOVEMENTS = "manage_movements"
    # Reports
    VIEW_REPORTS    = "view_reports"
    GENERATE_REPORTS = "generate_reports"
    # Appointments
    VIEW_APPOINTMENTS   = "view_appointments"
    MANAGE_APPOINTMENTS = "manage_appointments"
    # Expenses
    VIEW_EXPENSES   = "view_expenses"
    MANAGE_EXPENSES = "manage_expenses"
    # Requests
    VIEW_REQUESTS   = "view_requests"
    MANAGE_REQUESTS = "manage_requests"
    # Design Studio (branding documents) - deliberately split into
    # separate permissions rather than one combined toggle: ID cards
    # carry staff personal data, so a dealer may want to let someone
    # generate marketing flyers without also letting them generate ID
    # cards for other staff members.
    GENERATE_ID_CARDS = "generate_id_cards"
    GENERATE_MARKETING_MATERIALS = "generate_marketing_materials"
    GENERATE_BUSINESS_DOCS = "generate_business_docs"


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
