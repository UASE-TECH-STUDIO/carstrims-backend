from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class PaymentMethod(str, Enum):
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    CARD = "card"
    INSTALLMENT = "installment"
    OTHER = "other"


class SaleBase(BaseModel):
    carId: str
    dealerId: str
    sellingPrice: float
    paymentMethod: PaymentMethod = PaymentMethod.CASH
    buyerName: Optional[str] = None
    buyerPhone: Optional[str] = None
    buyerEmail: Optional[str] = None
    notes: Optional[str] = None


class SaleCreate(SaleBase):
    staffId: Optional[str] = None


class SaleTransactionInDB(SaleBase):
    id: Optional[str] = Field(None, alias="_id")
    transactionId: str
    staffId: Optional[str] = None
    purchasePrice: float
    profit: float
    expenses: float = 0.0
    netProfit: float
    partnerId: Optional[str] = None
    partnerShare: Optional[float] = None
    soldAt: datetime = Field(default_factory=datetime.utcnow)
    createdAt: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


class SaleResponse(SaleBase):
    id: str
    transactionId: str
    staffId: Optional[str] = None
    profit: float
    netProfit: float
    soldAt: datetime

    class Config:
        populate_by_name = True
