from fastapi import APIRouter, Depends
from app.auth.dependencies import get_current_dealer, get_current_dealer_or_staff
from app.modules.cctv.service import (
    add_camera, get_cameras, update_camera, delete_camera, ping_camera,
)
from app.modules.cctv.schemas import CameraCreateRequest, CameraUpdateRequest
from app.modules.dealers.service import get_dealer_by_user_id

router = APIRouter(prefix="/api/v1/cctv", tags=["CCTV"])


@router.post("/")
async def create_camera(
    data: CameraCreateRequest,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await add_camera(dealer["_id"], data.model_dump())


@router.get("/")
async def list_cameras(current_user: dict = Depends(get_current_dealer_or_staff)):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await get_cameras(dealer["_id"])


@router.patch("/{camera_id}")
async def edit_camera(
    camera_id: str,
    data: CameraUpdateRequest,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await update_camera(camera_id, dealer["_id"], data.model_dump(exclude_none=True))


@router.delete("/{camera_id}")
async def remove_camera(
    camera_id: str,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await delete_camera(camera_id, dealer["_id"])


@router.post("/{camera_id}/ping")
async def test_camera(
    camera_id: str,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await ping_camera(camera_id, dealer["_id"])
