from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from app.auth.dependencies import get_current_user
from app.auth.password import hash_password, verify_password
from app.auth.jwt import create_access_token, create_refresh_token
from app.modules.dealers.service import serialize_doc
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime
import random, string


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    fullName: str
    username: str
    email: str
    password: str
    phone: str
    whatsapp: Optional[str] = None
    role: str = "PUBLIC_USER"


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str


class ForgotPasswordRequest(BaseModel):
    email: str


class RefreshRequest(BaseModel):
    refreshToken: str


router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


def gen_user_id():
    return "USR-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


@router.post("/register")
async def register(data: RegisterRequest):
    db = get_db()

    existing = await db["users"].find_one({"email": data.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    existing_username = await db["users"].find_one({"username": data.username.lower()})
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already taken")

    status_val = "pending" if data.role == "DEALER_ADMIN" else "active"

    user_doc = {
        "userId": gen_user_id(),
        "fullName": data.fullName,
        "username": data.username.lower(),
        "email": data.email.lower(),
        "passwordHash": hash_password(data.password),
        "phone": data.phone,
        "whatsapp": data.whatsapp,
        "role": data.role,
        "status": status_val,
        "profilePicture": None,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    result = await db["users"].insert_one(user_doc)

    return {
        "message": "Account created successfully",
        "role": data.role,
        "status": status_val,
        "userId": user_doc["userId"],
    }


@router.post("/login")
async def login(data: LoginRequest):
    db = get_db()

    user = await db["users"].find_one({"email": data.email.lower()})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(data.password, user["passwordHash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if user.get("status") == "pending":
        raise HTTPException(status_code=403, detail="Account pending approval. You will be notified by email.")

    if user.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Account suspended. Contact support.")

    if user.get("status") == "deleted":
        raise HTTPException(status_code=403, detail="Account not found.")

    uid = str(user["_id"])

    dealer_id = None
    if user["role"] == "DEALER_ADMIN":
        dealer = await db["dealer_organizations"].find_one({"userId": uid})
        if dealer:
            dealer_id = str(dealer["_id"])

    access_token = create_access_token({"sub": uid, "role": user["role"]})
    refresh_token = create_refresh_token({"sub": uid})

    # Store refresh token
    await db["refresh_tokens"].insert_one({
        "userId": uid,
        "token": refresh_token,
        "createdAt": datetime.utcnow(),
    })

    return {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "userId": user.get("userId", uid),
        "fullName": user["fullName"],
        "email": user["email"],
        "role": user["role"],
        "dealerId": dealer_id,
        "profilePicture": user.get("profilePicture"),
    }


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return serialize_doc(current_user)


@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()

    if not verify_password(data.currentPassword, current_user["passwordHash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if len(data.newPassword) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")

    await db["users"].update_one(
        {"_id": ObjectId(str(current_user["_id"]))},
        {"$set": {"passwordHash": hash_password(data.newPassword), "updatedAt": datetime.utcnow()}},
    )
    return {"message": "Password changed successfully"}


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest):
    db = get_db()

    user = await db["users"].find_one({"email": data.email.lower()})
    if not user:
        return {"message": "If this email is registered, a temporary password has been sent."}

    temp_password = "Temp@" + "".join(random.choices(string.digits, k=6))

    await db["users"].update_one(
        {"_id": user["_id"]},
        {"$set": {"passwordHash": hash_password(temp_password), "updatedAt": datetime.utcnow()}},
    )

    # Notify user
    await db["notifications"].insert_one({
        "receiverId": str(user["_id"]),
        "type": "general",
        "title": "Password Reset",
        "message": f"Your temporary password is: {temp_password} — Please change it after logging in.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    return {
        "message": "Temporary password set successfully",
        "tempPassword": temp_password,
    }


@router.post("/refresh")
async def refresh_token(data: RefreshRequest):
    from app.auth.jwt import verify_refresh_token
    db = get_db()
    payload = verify_refresh_token(data.refreshToken)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    uid = payload.get("sub")
    user = await db["users"].find_one({"_id": ObjectId(uid)})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    access_token = create_access_token({"sub": uid, "role": user["role"]})
    return {"accessToken": access_token}


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    db = get_db()
    await db["refresh_tokens"].delete_many({"userId": str(current_user["_id"])})
    return {"message": "Logged out successfully"}