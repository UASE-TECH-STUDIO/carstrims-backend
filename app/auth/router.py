from fastapi import APIRouter, Depends, HTTPException
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
    emailOrPhone: Optional[str] = None  # accepts email OR phone
    email: Optional[str] = None         # backward compat
    password: str

class RegisterRequest(BaseModel):
    fullName: str
    username: str
    email: str
    password: str
    phone: str
    whatsapp: Optional[str] = None
    role: str = "PUBLIC_USER"
    notifyVia: Optional[str] = "email"  # "email" | "whatsapp" | "both"

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
    # Check email
    existing = await db["users"].find_one({"email": data.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    existing_username = await db["users"].find_one({"username": data.username.lower()})
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already taken")

    status_val = "pending_setup" if data.role == "DEALER_ADMIN" else "active"
    user_doc = {
        "userId": gen_user_id(),
        "fullName": data.fullName,
        "username": data.username.lower(),
        "email": data.email.lower(),
        "passwordHash": hash_password(data.password),
        "phone": data.phone,
        "whatsapp": data.whatsapp or data.phone,
        "role": data.role,
        "status": status_val,
        "profilePicture": None,
        "notifyVia": data.notifyVia or "email",
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }
    await db["users"].insert_one(user_doc)

    # Send welcome notification (non-blocking)
    try:
        from app.services.notifications import notify_registration
        import asyncio
        asyncio.create_task(notify_registration(user_doc))
    except Exception:
        pass

    # In-app welcome notification
    await db["notifications"].insert_one({
        "receiverId": user_doc["userId"],
        "type": "general",
        "title": "Welcome to CARSTRIMS! 🎉",
        "message": f"Hello {data.fullName}! Your account has been created. {'Complete your dealership setup to get started.' if data.role == 'DEALER_ADMIN' else 'Browse vehicles and message dealers directly.'}",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    return {"message": "Account created", "role": data.role, "status": status_val, "userId": user_doc["userId"]}


@router.post("/login")
async def login(data: LoginRequest):
    db = get_db()
    # Accept email OR phone
    login_id = data.emailOrPhone or data.email or ""
    login_id = login_id.strip().lower()

    # Try email first, then phone
    user = await db["users"].find_one({"email": login_id})
    if not user:
        user = await db["users"].find_one({"phone": login_id})
    if not user:
        user = await db["users"].find_one({"whatsapp": login_id})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(data.password, user["passwordHash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    status = user.get("status", "active")
    if status == "suspended":
        raise HTTPException(status_code=403, detail="Account suspended. Contact support.")
    if status == "deleted":
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

    access_token  = create_access_token({"sub": uid, "role": user["role"]})
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
        "userStatus": status,
        "dealerStatus": dealer_status,
        "hasDealerProfile": has_dealer_profile,
    }


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])
    result = serialize_doc(current_user)
    result.pop("passwordHash", None)
    if current_user.get("role") == "DEALER_ADMIN":
        dealer = await db["dealer_organizations"].find_one({"userId": uid})
        result["dealerStatus"]     = dealer.get("status") if dealer else None
        result["hasDealerProfile"] = bool(dealer)
    return result


@router.post("/change-password")
async def change_password(data: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    if not verify_password(data.currentPassword, current_user["passwordHash"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(data.newPassword) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    new_hash = hash_password(data.newPassword)
    await db["users"].update_one(
        {"_id": ObjectId(str(current_user["_id"]))},
        {"$set": {"passwordHash": new_hash, "updatedAt": datetime.utcnow()}},
    )
    return {"message": "Password changed successfully"}


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordRequest):
    db = get_db()
    user = await db["users"].find_one({"email": data.email.lower()})
    if not user:
        return {"message": "If this email is registered, a temporary password has been sent."}

    temp_password = "Temp@" + "".join(random.choices(string.digits, k=6))
    new_hash = hash_password(temp_password)
    await db["users"].update_one(
        {"_id": user["_id"]},
        {"$set": {"passwordHash": new_hash, "updatedAt": datetime.utcnow()}},
    )

    # Send via notifications service
    try:
        from app.services.notifications import notify_password_reset
        import asyncio
        asyncio.create_task(notify_password_reset(user, temp_password))
    except Exception:
        pass

    # Always save in-app notification
    await db["notifications"].insert_one({
        "receiverId": str(user["_id"]),
        "type": "general",
        "title": "Password Reset",
        "message": f"Your temporary password is: {temp_password} — Please change it after logging in.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    return {"message": "Temporary password set. Check email, WhatsApp, or your in-app notifications."}


@router.post("/forgot-password/options")
async def forgot_password_options(data: ForgotPasswordOptions):
    db = get_db()
    user = await db["users"].find_one({"email": data.email.lower()})
    if not user:
        return {"options": [{"type": "admin_message", "label": "Contact Support", "masked": "Send a request to CARSTRIMS admin"}]}

    options = []
    phone = user.get("whatsapp") or user.get("phone", "")
    if phone and len(phone) >= 4:
        options.append({"type": "whatsapp", "label": "WhatsApp OTP", "masked": f"WhatsApp ending in ****{phone[-4:]}"})
    email = user.get("email", "")
    if "@" in email:
        parts = email.split("@")
        masked = parts[0][:2] + "****" if len(parts[0]) > 2 else "****"
        options.append({"type": "email", "label": "Email Reset Link", "masked": masked + "@" + parts[1]})
    options.append({"type": "admin_message", "label": "Contact Admin", "masked": "Send a recovery request to CARSTRIMS admin"})
    return {"options": options}


@router.post("/forgot-password/send")
async def forgot_password_send(data: ForgotPasswordSend):
    db = get_db()
    user = await db["users"].find_one({"email": data.email.lower()})

    if data.method == "admin_message":
        admins = await db["users"].find({"role": "SYSTEM_ADMIN"}).to_list(5)
        for admin in admins:
            await db["notifications"].insert_one({
                "receiverId": str(admin["_id"]),
                "type": "password_recovery",
                "title": "Password Recovery Request",
                "message": f"User {data.email} has requested password recovery. Use !password in their chat to reset.",
                "isRead": False,
                "createdAt": datetime.utcnow(),
            })
        return {"message": "Recovery request sent to admin"}

    if not user:
        return {"message": "Recovery sent if account exists"}

    temp_password = "Reset@" + "".join(random.choices(string.ascii_letters + string.digits, k=8))
    new_hash = hash_password(temp_password)
    await db["users"].update_one(
        {"_id": user["_id"]},
        {"$set": {"passwordHash": new_hash, "updatedAt": datetime.utcnow()}},
    )

    # Send via method chosen
    try:
        from app.services.notifications import send_email, send_whatsapp, email_base
        if data.method == "email":
            html = email_base(
                "Your New Password — CARSTRIMS",
                f"""
                <p>Hello {user.get('fullName','')},</p>
                <div style="background:#F5F5F5;border-radius:8px;padding:1.25rem;text-align:center;margin:1rem 0">
                  <p style="margin:0;font-size:0.8rem;color:#888">TEMPORARY PASSWORD</p>
                  <p style="margin:0.5rem 0 0;font-size:1.5rem;font-family:monospace;font-weight:bold">{temp_password}</p>
                </div>
                <p style="color:#DC2626;font-size:0.875rem">⚠️ Change this immediately after login.</p>
                <a href="https://carstrims-app.vercel.app/login" style="display:inline-block;background:#F47B20;color:#fff;text-decoration:none;padding:0.875rem 2rem;border-radius:8px;font-weight:bold">Login Now →</a>
                """,
            )
            import asyncio
            asyncio.create_task(send_email(user["email"], "CARSTRIMS — New Temporary Password", html))
        elif data.method == "whatsapp":
            phone = user.get("whatsapp") or user.get("phone", "")
            import asyncio
            asyncio.create_task(send_whatsapp(phone,
                f"🔑 *CARSTRIMS Password Reset*\n\n"
                f"Your temporary password: *{temp_password}*\n\n"
                f"⚠️ Please login and change it.\n\n"
                f"👉 https://carstrims-app.vercel.app/login"
            ))
    except Exception:
        pass

    await db["notifications"].insert_one({
        "receiverId": str(user["_id"]),
        "type": "general",
        "title": "Password Reset",
        "message": f"Temporary password: {temp_password} — Change it after login.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    return {"message": "Temporary password sent."}


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
    return {"message": "Logged out"}
