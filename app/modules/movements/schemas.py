from pydantic import BaseModel
from typing import Optional


class MovementCreateRequest(BaseModel):
    carId: str
    takenByName: str
    takenByPhone: str
    purpose: str
    staffReleasedId: Optional[str] = None
    approvedById: Optional[str] = None
    expectedReturnTime: Optional[str] = None
    keyLocation: Optional[str] = None
    notes: Optional[str] = None
    idCardUrl: Optional[str] = None


class VehicleReturnRequest(BaseModel):
    staffReceivedId: Optional[str] = None
    conditionOnReturn: Optional[str] = None
