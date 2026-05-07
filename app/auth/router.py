from fastapi import APIRouter, Depends, status, HTTPException
from app.auth.schemas import (
    RegisterRequest, LoginRequest, TokenResponse,
    RefreshRequest, ChangePasswordRequest, ForgotPasswordRequest,
)
from app.auth.service import register_user, login_user, refresh_access_token
from app.auth.forgot_password import forgot_password
from app.auth.dependencies import get_current_user
from app.auth.password import verify_password, hash_password
from app.database.connection import get_db
from datetime import datetime

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


# -----------------------------
# REGISTER
# -----------------------------
@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest):
    user = await register_user(data)

    return {
        "message": "Registration successful",
        "userId": user["userId"],   # ✅ FIXED (was _id before)
        "role": user["role"],
        "status": user.get("status", "active"),
        "requiresApproval": user.get("status") == "pending",
    }


# -----------------------------
# LOGIN
# -----------------------------
@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest):
    return await login_user(data)


# -----------------------------
# REFRESH TOKEN
# -----------------------------
@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest):
    return await refresh_access_token(data.refreshToken)


# -----------------------------
# GET CURRENT USER
# -----------------------------
@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "userId": str(current_user["_id"]),
        "fullName": current_user["fullName"],
        "email": current_user["email"],
        "username": current_user.get("username"),
        "role": current_user["role"],
        "status": current_user.get("status"),
        "dealerId": current_user.get("dealerId"),
        "profilePicture": current_user.get("profilePicture"),
        "phone": current_user.get("phone"),
        "whatsapp": current_user.get("whatsapp"),
        "createdAt": current_user.get("createdAt"),
        "lastLogin": current_user.get("lastLogin"),
    }


# -----------------------------
# FORGOT PASSWORD
# -----------------------------
@router.post("/forgot-password")
async def forgot_password_endpoint(data: ForgotPasswordRequest):
    return await forgot_password(data.email)


# -----------------------------
# CHANGE PASSWORD
# -----------------------------
@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    if not verify_password(data.currentPassword, current_user["passwordHash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    db = get_db()

    await db["users"].update_one(
        {"_id": current_user["_id"]},
        {
            "$set": {
                "passwordHash": hash_password(data.newPassword),
                "updatedAt": datetime.utcnow(),
            }
        },
    )

    return {"message": "Password changed successfully"}


# -----------------------------
# LOGOUT
# -----------------------------
@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    return {"message": "Logged out successfully"}