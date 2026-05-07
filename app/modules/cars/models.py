from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class CarStatus(str, Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    SOLD = "sold"
    OUT_FOR_INSPECTION = "out_for_inspection"
    IN_REPAIR = "in_repair"
    ON_PROMOTION = "on_promotion"
    DRAFT = "draft"


class OwnerType(str, Enum):
    DEALER = "dealer"
    PARTNER = "partner"


class CarBase(BaseModel):
    brand: str
    model: str
    year: int
    color: str
    mileage: Optional[float] = None
    vin: Optional[str] = None
    engineType: Optional[str] = None
    transmission: Optional[str] = None
    fuelType: Optional[str] = None
    condition: Optional[str] = None
    description: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None


class CarCreate(CarBase):
    dealerId: str
    ownerId: str
    ownerType: OwnerType = OwnerType.DEALER
    purchasePrice: float
    sellingPrice: float
    promoPrice: Optional[float] = None
    minNegotiationPrice: Optional[float] = None


class CarInDB(CarBase):
    id: Optional[str] = Field(None, alias="_id")
    carId: str
    dealerId: str
    ownerId: str
    ownerType: OwnerType
    purchasePrice: float
    sellingPrice: float
    promoPrice: Optional[float] = None
    minNegotiationPrice: Optional[float] = None
    estimatedProfit: float = 0.0
    actualProfit: Optional[float] = None
    status: CarStatus = CarStatus.DRAFT
    images: List[str] = []
    video: Optional[str] = None
    qrCode: Optional[str] = None
    viewCount: int = 0
    likeCount: int = 0
    isFeatured: bool = False
    soldAt: Optional[datetime] = None
    soldBy: Optional[str] = None
    createdAt: datetime = Field(default_factory=datetime.utcnow)
    updatedAt: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


class CarResponse(CarBase):
    id: str
    carId: str
    dealerId: str
    ownerId: str
    ownerType: OwnerType
    sellingPrice: float
    promoPrice: Optional[float] = None
    estimatedProfit: float
    status: CarStatus
    images: List[str]
    video: Optional[str] = None
    viewCount: int
    likeCount: int
    createdAt: datetime

    class Config:
        populate_by_name = True
