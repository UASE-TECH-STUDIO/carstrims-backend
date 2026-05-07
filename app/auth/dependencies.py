from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.auth.jwt import verify_access_token
from app.database.connection import get_db
from app.modules.users.models import UserRole
from bson import ObjectId

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials
    payload = verify_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    db = get_db()
    user = await db["users"].find_one({"_id": ObjectId(payload.get("sub"))})

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if user.get("status") == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been suspended",
        )

    return user


def require_roles(*roles: UserRole):
    async def role_checker(current_user: dict = Depends(get_current_user)):
        if current_user.get("role") not in [r.value for r in roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action",
            )
        return current_user
    return role_checker


async def get_current_dealer(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in [
        UserRole.DEALER_ADMIN.value,
        UserRole.SYSTEM_ADMIN.value,
    ]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Dealer account required",
        )
    return current_user


async def get_current_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != UserRole.SYSTEM_ADMIN.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="System admin access required",
        )
    return current_user


async def get_current_staff(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in [
        UserRole.DEALER_STAFF.value,
        UserRole.DEALER_ADMIN.value,
        UserRole.SYSTEM_ADMIN.value,
    ]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff account required",
        )
    return current_user
