from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException, status

from app.database.connection import get_db
from app.auth.password import hash_password, verify_password
from app.auth.jwt import create_access_token, create_refresh_token, verify_refresh_token
from app.auth.schemas import RegisterRequest, LoginRequest


# ----------------------------
# REGISTER USER
# ----------------------------
async def register_user(data: RegisterRequest) -> dict:
    db = get_db()

    # Email check
    if await db["users"].find_one({"email": data.email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    # Username check
    if await db["users"].find_one({"username": data.username}):
        raise HTTPException(status_code=400, detail="Username already taken")

    # Password validation
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    # 🔥 IMPORTANT FIX: role is now STRING from frontend
    role = data.role

    # Dealer pending approval logic (safe string comparison)
    status_value = "pending" if role == "DEALER_ADMIN" else "active"

    user_doc = {
        "fullName": data.fullName,
        "username": data.username,
        "email": data.email,
        "phone": data.phone,
        "whatsapp": data.whatsapp,
        "address": data.address,
        "role": role,
        "passwordHash": hash_password(data.password),
        "status": status_value,
        "dealerId": None,
        "profilePicture": None,
        "isEmailVerified": False,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
        "lastLogin": None,
    }

    result = await db["users"].insert_one(user_doc)
    user_doc["_id"] = result.inserted_id

    # IMPORTANT: return safe response only
    return {
        "userId": str(result.inserted_id),
        "fullName": user_doc["fullName"],
        "email": user_doc["email"],
        "role": user_doc["role"],
    }


# ----------------------------
# LOGIN USER
# ----------------------------
async def login_user(data: LoginRequest) -> dict:
    db = get_db()

    user = await db["users"].find_one({"email": data.email})

    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not verify_password(data.password, user["passwordHash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # update last login
    await db["users"].update_one(
        {"_id": user["_id"]},
        {"$set": {"lastLogin": datetime.utcnow()}}
    )

    user_id = str(user["_id"])

    token_payload = {
        "sub": user_id,
        "role": user["role"],
        "email": user["email"],
    }

    return {
        "accessToken": create_access_token(token_payload),
        "refreshToken": create_refresh_token(token_payload),
        "userId": user_id,
        "fullName": user["fullName"],
        "email": user["email"],
        "role": user["role"],
        "dealerId": user.get("dealerId"),
    }


# ----------------------------
# REFRESH TOKEN
# ----------------------------
async def refresh_access_token(refresh_token: str) -> dict:
    payload = verify_refresh_token(refresh_token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    db = get_db()
    user = await db["users"].find_one({"_id": ObjectId(payload["sub"])})

    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    user_id = str(user["_id"])

    token_payload = {
        "sub": user_id,
        "role": user["role"],
        "email": user["email"],
    }

    return {
        "accessToken": create_access_token(token_payload),
        "refreshToken": create_refresh_token(token_payload),
        "userId": user_id,
        "fullName": user["fullName"],
        "email": user["email"],
        "role": user["role"],
        "dealerId": user.get("dealerId"),
    }