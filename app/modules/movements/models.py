from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class MovementPurpose(str, Enum):
    TEST_DRIVE = "test_drive"
    INSPECTION = "inspection"
    DELIVERY = "delivery"
    WORKSHOP = "workshop"
    PERSONAL_USE = "personal_use"
    OTHER = "other"


class MovementStatus(str, Enum):
    OUT = "out"
    RETURNED = "returned"
    OVERDUE = "overdue"


class VehicleMovementBase(BaseModel):
    carId: str
    dealerId: str
    takenByName: str
    takenByPhone: str
    purpose: MovementPurpose
    staffReleasedId: str
    approvedById: Optional[str] = None
    expectedReturnTime: Optional[datetime] = None
    notes: Optional[str] = None


class MovementCreate(VehicleMovementBase):
    idCardUrl: Optional[str] = None


class VehicleMovementInDB(VehicleMovementBase):
    id: Optional[str] = Field(None, alias="_id")
    movementId: str
    idCardUrl: Optional[str] = None
    status: MovementStatus = MovementStatus.OUT
    timeOut: datetime = Field(default_factory=datetime.utcnow)
    timeReturned: Optional[datetime] = None
    staffReceivedId: Optional[str] = None
    conditionOnReturn: Optional[str] = None
    keyLocation: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


class MovementResponse(VehicleMovementBase):
    id: str
    movementId: str
    status: MovementStatus
    timeOut: datetime
    timeReturned: Optional[datetime] = None
    createdAt: datetime

    class Config:
        populate_by_name = True
