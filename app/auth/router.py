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

class ForgotPasswordOptions(BaseModel):
    email: str

class ForgotPasswordSend(BaseModel):
    email: str
    method: str


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
    # Dealers start as pending_setup — they CAN login to complete setup
    # After setup they become awaiting_approval for admin review
    # All other roles go straight to active
    status_val = "pending_setup" if data.role == "DEALER_ADMIN" else "active"
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
    await db["users"].insert_one(user_doc)
    return {"message": "Account created successfully", "role": data.role, "status": status_val, "userId": user_doc["userId"]}


@router.post("/login")
async def login(data: LoginRequest):
    db = get_db()
    user = await db["users"].find_one({"email": data.email.lower()})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(data.password, user["passwordHash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user_status = user.get("status", "active")
    # ONLY block suspended or deleted accounts
    # pending_setup, awaiting_approval, pending — all CAN login
    if user_status == "suspended":
        raise HTTPException(status_code=403, detail="Account suspended. Contact support.")
    if user_status == "deleted":
        raise HTTPException(status_code=403, detail="Account not found.")
    uid = str(user["_id"])
    dealer_id = None
    dealer_status = None
    has_dealer_profile = False
    if user["role"] == "DEALER_ADMIN":
        dealer = await db["dealer_organizations"].find_one({"userId": uid})
        if dealer:
            dealer_id = str(dealer["_id"])
            dealer_status = dealer.get("status", "awaiting_approval")
            has_dealer_profile = True
    access_token = create_access_token({"sub": uid, "role": user["role"]})
    refresh_token = create_refresh_token({"sub": uid})
    await db["refresh_tokens"].insert_one({"userId": uid, "token": refresh_token, "createdAt": datetime.utcnow()})
    await db["users"].update_one({"_id": user["_id"]}, {"$set": {"lastLogin": datetime.utcnow()}})
    return {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "userId": user.get("userId", uid),
        "fullName": user["fullName"],
        "email": user["email"],
        "role": user["role"],
        "dealerId": dealer_id,
        "profilePicture": user.get("profilePicture"),
        "userStatus": user_status,
        "dealerStatus": dealer_status,
        "hasDealerProfile": has_dealer_profile,
    }


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])
    result = serialize_doc(current_user)
    if current_user.get("role") == "DEALER_ADMIN":
        dealer = await db["dealer_organizations"].find_one({"userId": uid})
        if dealer:
            result["dealerStatus"] = dealer.get("status")
            result["hasDealerProfile"] = True
        else:
            result["dealerStatus"] = None
            result["hasDealerProfile"] = False
    return result


@router.post("/change-password")
async def change_password(data: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    if not verify_password(data.currentPassword, current_user["passwordHash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(data.newPassword) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    await db["users"].update_one({"_id": ObjectId(str(current_user["_id"]))}, {"$set": {"passwordHash": hash_password(data.newPassword), "updatedAt": datetime.utcnow()}})
    return {"message": "Password changed successfully"}


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest):
    db = get_db()
    user = await db["users"].find_one({"email": data.email.lower()})
    if not user:
        return {"message": "If this email is registered, a temporary password has been sent."}
    temp_password = "Temp@" + "".join(random.choices(string.digits, k=6))
    await db["users"].update_one({"_id": user["_id"]}, {"$set": {"passwordHash": hash_password(temp_password), "updatedAt": datetime.utcnow()}})
    await db["notifications"].insert_one({"receiverId": str(user["_id"]), "type": "general", "title": "Password Reset", "message": "Your temporary password is: " + temp_password + " - Please change it after logging in.", "isRead": False, "createdAt": datetime.utcnow()})
    return {"message": "Temporary password set successfully", "tempPassword": temp_password}


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


@router.post("/forgot-password/options")
async def forgot_password_options(data: ForgotPasswordOptions):
    db = get_db()
    user = await db["users"].find_one({"email": data.email.lower()})
    if not user:
        return {"options": [{"type": "admin_message", "label": "Contact Support", "masked": "Send a request to CARSTRIMS admin for manual verification"}]}
    options = []
    whatsapp = user.get("whatsapp") or user.get("phone")
    if whatsapp and len(whatsapp) >= 4:
        options.append({"type": "whatsapp", "label": "Send to WhatsApp", "masked": "WhatsApp ending in ****" + whatsapp[-4:]})
    email = user.get("email", "")
    if "@" in email:
        parts = email.split("@")
        masked_name = parts[0][:2] + "****" if len(parts[0]) > 2 else "****"
        options.append({"type": "email", "label": "Send to Email", "masked": masked_name + "@" + parts[1]})
    options.append({"type": "admin_message", "label": "Contact Admin Directly", "masked": "Send a recovery request to CARSTRIMS admin for identity verification"})
    return {"options": options}


@router.post("/forgot-password/send")
async def forgot_password_send(data: ForgotPasswordSend):
    import secrets
    db = get_db()
    user = await db["users"].find_one({"email": data.email.lower()})
    if data.method == "admin_message":
        admins = await db["users"].find({"role": "SYSTEM_ADMIN"}).to_list(5)
        for admin in admins:
            await db["notifications"].insert_one({"receiverId": str(admin["_id"]), "type": "password_recovery", "title": "Password Recovery Request", "message": "User with email " + data.email + " has requested password recovery.", "isRead": False, "data": {"email": data.email}, "createdAt": datetime.utcnow()})
        return {"message": "Recovery request sent to admin"}
    if not user:
        return {"message": "Recovery sent if account exists"}
    if data.method in ("whatsapp", "email"):
        reset_token = secrets.token_urlsafe(32)
        await db["password_reset_tokens"].insert_one({"userId": str(user["_id"]), "email": user["email"], "token": reset_token, "createdAt": datetime.utcnow(), "used": False})
        await db["notifications"].insert_one({"receiverId": str(user["_id"]), "type": "password_recovery", "title": "Password Recovery Requested", "message": "Someone requested a password reset via " + data.method + ".", "isRead": False, "data": {"token": reset_token, "method": data.method}, "createdAt": datetime.utcnow()})
    return {"message": "Recovery instructions sent via " + data.method}
