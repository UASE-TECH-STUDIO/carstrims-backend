from fastapi import APIRouter, Depends, Query
from app.auth.dependencies import get_current_dealer, get_current_dealer_or_staff, get_current_admin
from app.modules.reports.service import get_dealer_reports, get_admin_platform_reports
from app.modules.dealers.service import get_dealer_by_user_id

router = APIRouter(prefix="/api/v1/reports", tags=["Reports"])


@router.get("/dealer")
async def dealer_reports(
    period: str = Query("month", enum=["week", "month", "year"]),
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await get_dealer_reports(dealer["_id"], period)


@router.get("/admin/platform")
async def platform_reports(current_user: dict = Depends(get_current_admin)):
    return await get_admin_platform_reports()


@router.get("/dealer/car/{car_id}")
async def dealer_car_report(
    car_id: str,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    """Full per-car financial report."""
    from app.modules.dealers.service import get_dealer_by_user_id
    from app.modules.cars.sale_service import get_car_financial_report
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    return await get_car_financial_report(dealer["_id"], car_id)
