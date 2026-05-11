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
        "message": f"Your temporary password is: {temp_password} â€” Please change it after logging in.",
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

class ForgotPasswordOptions(BaseModel):
    email: str


class ForgotPasswordSend(BaseModel):
    email: str
    method: str  # whatsapp | email | admin_message


@router.post("/forgot-password/options")
async def forgot_password_options(data: ForgotPasswordOptions):
    """Return masked recovery options for the account."""
    db = get_db()

    user = await db["users"].find_one({"email": data.email.lower()})
    if not user:
        # Return generic option - don't reveal if email exists
        return {
            "options": [
                {
                    "type": "admin_message",
                    "label": "Contact Support",
                    "masked": "Send a request to CARSTRIMS admin for manual verification",
                }
            ]
        }

    options = []

    # WhatsApp option
    whatsapp = user.get("whatsapp") or user.get("phone")
    if whatsapp and len(whatsapp) >= 4:
        last4 = whatsapp[-4:]
        options.append({
            "type": "whatsapp",
            "label": "Send to WhatsApp",
            "masked": f"WhatsApp ending in ****{last4}",
        })

    # Email option (masked)
    email = user.get("email", "")
    if "@" in email:
        parts = email.split("@")
        masked_name = parts[0][:2] + "****" if len(parts[0]) > 2 else "****"
        options.append({
            "type": "email",
            "label": "Send to Email",
            "masked": f"{masked_name}@{parts[1]}",
        })

    # Always offer admin contact
    options.append({
        "type": "admin_message",
        "label": "Contact Admin Directly",
        "masked": "Send a recovery request to CARSTRIMS admin for identity verification",
    })

    return {"options": options}


@router.post("/forgot-password/send")
async def forgot_password_send(data: ForgotPasswordSend):
    """Process recovery request via chosen method."""
    db = get_db()

    user = await db["users"].find_one({"email": data.email.lower()})

    if data.method == "admin_message":
        # Create a notification for all super admins
        admins = await db["users"].find({"role": "SYSTEM_ADMIN"}).to_list(5)
        for admin in admins:
            await db["notifications"].insert_one({
                "receiverId": str(admin["_id"]),
                "type": "password_recovery",
                "title": "Password Recovery Request",
                "message": f"User with email {data.email} has requested password recovery. Please verify their identity and assist them.",
                "isRead": False,
                "data": {"email": data.email},
                "createdAt": datetime.utcnow(),
            })
        # Also create a support conversation
        if user:
            for admin in admins[:1]:  # Message first admin
                admin_id = str(admin["_id"])
                user_id = str(user["_id"])
                conv_id = f"CONV-RECOVERY-{user_id[:6]}"
                existing = await db["conversations"].find_one({"conversationId": conv_id})
                if not existing:
                    await db["conversations"].insert_one({
                        "conversationId": conv_id,
                        "participants": [admin_id, user_id],
                        "type": "support",
                        "lastMessage": "Password recovery request",
                        "lastMessageAt": datetime.utcnow(),
                        "createdAt": datetime.utcnow(),
                    })
                await db["messages"].insert_one({
                    "messageId": "MSG-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8)),
                    "conversationId": conv_id,
                    "senderId": user_id,
                    "receiverId": admin_id,
                    "message": f"I need help recovering my account ({data.email}). I cannot access my password.",
                    "isRead": False,
                    "createdAt": datetime.utcnow(),
                })
        return {"message": "Recovery request sent to admin"}

    if not user:
        # Silently succeed - don't reveal account existence
        return {"message": "Recovery sent if account exists"}

    if data.method in ("whatsapp", "email"):
        # Generate a secure temp token (not exposed directly)
        import secrets
        reset_token = secrets.token_urlsafe(32)
        await db["password_reset_tokens"].insert_one({
            "userId": str(user["_id"]),
            "email": user["email"],
            "token": reset_token,
            "createdAt": datetime.utcnow(),
            "expiresAt": datetime.utcnow().replace(
                minute=datetime.utcnow().minute + 30
            ),
            "used": False,
        })
        # Store notification with token (simulates sending)
        await db["notifications"].insert_one({
            "receiverId": str(user["_id"]),
            "type": "password_recovery",
            "title": "Password Recovery Requested",
            "message": f"Someone requested a password reset for your account. If this was you, contact support or use the link sent to your registered {data.method}. If not, please secure your account immediately.",
            "isRead": False,
            "data": {"token": reset_token, "method": data.method},
            "createdAt": datetime.utcnow(),
        })

    return {"message": f"Recovery instructions sent via {data.method}"}