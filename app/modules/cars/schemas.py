from pydantic import BaseModel
from typing import Optional


class CarCreateRequest(BaseModel):
    vehicleType: Optional[str] = "car"  # car, motorcycle, tricycle, bus, truck, van
    brand: str
    model: str
    year: int
    color: Optional[str] = None
    mileage: Optional[float] = None
    vin: Optional[str] = None
    engineType: Optional[str] = None
    transmission: Optional[str] = None
    fuelType: Optional[str] = None
    condition: Optional[str] = "used"
    description: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    purchasePrice: Optional[float] = None
    sellingPrice: float
    promoPrice: Optional[float] = None
    minNegotiationPrice: Optional[float] = None
    ownerType: Optional[str] = "dealer"
    ownerId: Optional[str] = None


class CarUpdateRequest(BaseModel):
    vehicleType: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    color: Optional[str] = None
    mileage: Optional[float] = None
    vin: Optional[str] = None
    engineType: Optional[str] = None
    transmission: Optional[str] = None
    fuelType: Optional[str] = None
    condition: Optional[str] = None
    description: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    purchasePrice: Optional[float] = None
    sellingPrice: Optional[float] = None
    promoPrice: Optional[float] = None
    minNegotiationPrice: Optional[float] = None
    status: Optional[str] = None


class SellCarRequest(BaseModel):
    sellingPrice: float
    buyerName: Optional[str] = None
    buyerPhone: Optional[str] = None
    paymentMethod: Optional[str] = "cash"
    notes: Optional[str] = None
