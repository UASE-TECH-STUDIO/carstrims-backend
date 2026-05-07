from pydantic import BaseModel
from typing import Optional


class PartnerRequestCreate(BaseModel):
    dealerId: str


class PartnerActionRequest(BaseModel):
    reason: Optional[str] = None


class AssignCarRequest(BaseModel):
    carId: str
