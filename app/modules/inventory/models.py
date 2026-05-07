from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class ExpenseCategory(str, Enum):
    REPAIR = "repair"
    FUEL = "fuel"
    TRANSPORT = "transport"
    REGISTRATION = "registration"
    MARKETING = "marketing"
    STAFF_PAYMENT = "staff_payment"
    CUSTOMS = "customs"
    CAR_WASH = "car_wash"
    MISCELLANEOUS = "miscellaneous"


class ExpenseBase(BaseModel):
    dealerId: str
    carId: Optional[str] = None
    category: ExpenseCategory
    amount: float
    description: Optional[str] = None
    receiptUrl: Optional[str] = None


class ExpenseCreate(ExpenseBase):
    recordedById: str


class ExpenseRecordInDB(ExpenseBase):
    id: Optional[str] = Field(None, alias="_id")
    expenseId: str
    recordedById: str
    createdAt: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        populate_by_name = True


class ExpenseResponse(ExpenseBase):
    id: str
    expenseId: str
    recordedById: str
    createdAt: datetime

    class Config:
        populate_by_name = True
