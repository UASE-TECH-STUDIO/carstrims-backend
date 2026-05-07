from fastapi import APIRouter, Depends, Body
from typing import Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_user
from app.modules.users.user_service import (
    update_user_profile, add_favorite, remove_favorite, get_favorites,
    create_special_request, get_user_requests, respond_to_request,
    create_appointment, get_user_appointments, toggle_like, get_user_likes,
    get_dealer_requests,
)
from app.modules.dealers.service import get_dealer_by_user_id


class ProfileUpdate(BaseModel):
    fullName: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None


class SpecialRequestCreate(BaseModel):
    dealerId: Optional[str] = None
    carBrand: str
    carModel: str
    carYear: Optional[int] = None
    carColor: Optional[str] = None
    budget: Optional[float] = None
    paymentType: Optional[str] = "full"
    description: Optional[str] = None


class AppointmentCreate(BaseModel):
    dealerId: str
    type: Optional[str] = "showroom_visit"
    scheduledAt: Optional[str] = None
    notes: Optional[str] = None


class DealerResponseBody(BaseModel):
    response: str
    progressNote: Optional[str] = None


router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.patch("/profile")
async def update_profile(data: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    return await update_user_profile(str(current_user["_id"]), data.model_dump(exclude_none=True))


@router.get("/favorites")
async def list_favorites(current_user: dict = Depends(get_current_user)):
    return await get_favorites(str(current_user["_id"]))


@router.post("/favorites/{car_id}")
async def like_car(car_id: str, current_user: dict = Depends(get_current_user)):
    return await add_favorite(str(current_user["_id"]), car_id)


@router.delete("/favorites/{car_id}")
async def unlike_car(car_id: str, current_user: dict = Depends(get_current_user)):
    return await remove_favorite(str(current_user["_id"]), car_id)


@router.get("/likes")
async def my_likes(current_user: dict = Depends(get_current_user)):
    return await get_user_likes(str(current_user["_id"]))


@router.post("/likes/{car_id}")
async def toggle_car_like(car_id: str, current_user: dict = Depends(get_current_user)):
    return await toggle_like(str(current_user["_id"]), car_id)


@router.post("/requests")
async def create_request(data: SpecialRequestCreate, current_user: dict = Depends(get_current_user)):
    return await create_special_request(str(current_user["_id"]), data.model_dump())


@router.get("/requests")
async def my_requests(current_user: dict = Depends(get_current_user)):
    return await get_user_requests(str(current_user["_id"]))


@router.get("/requests/dealer")
async def dealer_requests(current_user: dict = Depends(get_current_user)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await get_dealer_requests(dealer["_id"])


@router.post("/requests/{request_id}/respond")
async def respond_request(
    request_id: str,
    data: DealerResponseBody,
    current_user: dict = Depends(get_current_user),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]))
    return await respond_to_request(request_id, dealer["_id"], data.response, data.progressNote)


@router.post("/appointments")
async def book_appointment(data: AppointmentCreate, current_user: dict = Depends(get_current_user)):
    return await create_appointment(str(current_user["_id"]), data.model_dump())


@router.get("/appointments")
async def my_appointments(current_user: dict = Depends(get_current_user)):
    return await get_user_appointments(str(current_user["_id"]))
