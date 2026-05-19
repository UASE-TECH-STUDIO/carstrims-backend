"""
Forgot password service — generates a temp password and delivers it via
SMS (Twilio), WhatsApp (Twilio Sandbox), Email (Resend API), or Admin message.
"""
import os, random, string, httpx
from datetime import datetime
from fastapi import HTTPException
from app.database.connection import get_db
from app.auth.password import hash_password

# ── Config from environment ──────────────────────────────────
RESEND_API_KEY  = os.getenv("RESEND_API_KEY", "")
RESEND_FROM     = os.getenv("RESEND_FROM", "CARSTRIMS <onboarding@resend.dev>")
TWILIO_SID      = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_SMS_FROM = os.getenv("TWILIO_PHONE_NUMBER", "")
TWILIO_WA_FROM  = os.getenv("TWILIO_WA_FROM", "whatsapp:+14155238886")
TWILIO_WA_JOIN  = os.getenv("TWILIO_WA_JOIN", "join ants-whistle")


def _gen_temp_password(length: int = 10) -> str:
    chars = string.ascii_letters + string.digits
    return "Temp@" + "".join(random.choices(chars, k=length))


async def get_recovery_options(email: str) -> dict:
    db = get_db()
    user = await db["users"].find_one({"email": email.lower().strip()})
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email address.")

    options = []

    if user.get("phone"):
        ph = user["phone"]
        masked = ph[:4] + "****" + ph[-3:] if len(ph) > 7 else ph
        options.append({
            "type": "sms",
            "label": "Send via SMS",
            "masked": f"Send a new password by text message to {masked}",
        })

    if user.get("whatsapp") or user.get("phone"):
        wa = user.get("whatsapp") or user.get("phone")
        masked = wa[:4] + "****" + wa[-3:] if len(wa) > 7 else wa
        options.append({
            "type": "whatsapp",
            "label": "Send via WhatsApp",
            "masked": f"Send a new password to WhatsApp {masked}",
        })

    if user.get("email"):
        parts = user["email"].split("@")
        masked_email = parts[0][:2] + "***@" + parts[1] if len(parts) > 1 else user["email"]
        options.append({
            "type": "email",
            "label": "Send to Email",
            "masked": f"Send a new password to {masked_email}",
        })

    options.append({
        "type": "admin_message",
        "label": "Contact Admin Support",
        "masked": "Request manual identity verification from the CARSTRIMS admin team",
    })

    return {"options": options}


async def send_recovery(email: str, method: str) -> dict:
    db = get_db()
    user = await db["users"].find_one({"email": email.lower().strip()})
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email address.")

    temp_password = _gen_temp_password()
    hashed = hash_password(temp_password)

    await db["users"].update_one(
        {"_id": user["_id"]},
        {"$set": {"passwordHash": hashed, "tempPassword": True, "updatedAt": datetime.utcnow()}},
    )

    if method == "email":
        ok = await _send_email_resend(user["email"], user.get("fullName", "User"), temp_password)
        if not ok:
            raise HTTPException(
                status_code=500,
                detail="Failed to send email. Please try WhatsApp or contact Admin Support."
            )

    elif method == "sms":
        phone = user.get("phone")
        if not phone:
            raise HTTPException(
                status_code=400,
                detail="No phone number on this account. Try Email or Admin Support."
            )
        ok = await _send_sms_twilio(phone, temp_password)
        if not ok:
            raise HTTPException(
                status_code=500,
                detail="Failed to send SMS. Please try Email or contact Admin Support."
            )

    elif method == "whatsapp":
        wa = user.get("whatsapp") or user.get("phone")
        if not wa:
            raise HTTPException(
                status_code=400,
                detail="No WhatsApp number on this account. Try Email or Admin Support."
            )
        ok = await _send_whatsapp_twilio(wa, temp_password, user.get("fullName", "User"))
        if not ok:
            raise HTTPException(
                status_code=500,
                detail="Failed to send WhatsApp message. Make sure you have joined the sandbox by sending 'join ants-whistle' to +14155238886 on WhatsApp first."
            )

    elif method == "admin_message":
        await _notify_admin(db, user, temp_password)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown recovery method: {method}")

    return {"message": f"Recovery sent via {method}"}


async def _send_email_resend(to_email: str, name: str, temp_password: str) -> bool:
    """Send via Resend API (RESEND_API_KEY from .env)."""
    if not RESEND_API_KEY:
        print(f"[DEV - no RESEND_API_KEY] Password reset for {to_email}: {temp_password}")
        return True  # dev mode: pretend success so no error shown

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;padding:28px;background:#fff">
      <h2 style="color:#F47B20;letter-spacing:0.15em;margin-bottom:4px">CARSTRIMS</h2>
      <p style="color:#737373;font-size:0.8rem;margin-bottom:24px">Built by UASE TECH STUDIO</p>
      <p style="color:#1A1A1A">Hi {name},</p>
      <p style="color:#404040">Your account password has been temporarily reset. Use the password below to sign in:</p>
      <div style="background:#F5F5F5;border:2px solid #F47B20;border-radius:10px;padding:22px;text-align:center;margin:22px 0">
        <span style="font-size:1.6rem;font-weight:700;letter-spacing:0.12em;color:#1A1A1A;font-family:monospace">{temp_password}</span>
      </div>
      <p style="color:#DC2626;font-weight:600">Change this password immediately after logging in from your Settings page.</p>
      <p style="color:#737373;font-size:0.85rem">If you did not request a password reset, contact support@carstrims.com immediately.</p>
      <hr style="border:none;border-top:1px solid #E5E5E5;margin:24px 0"/>
      <p style="color:#A3A3A3;font-size:0.72rem">CARSTRIMS - Nigeria Premier Vehicle Marketplace - Built by UASE TECH STUDIO</p>
    </div>
    """

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            res = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": RESEND_FROM,
                    "to": [to_email],
                    "subject": "CARSTRIMS - Your New Temporary Password",
                    "html": html,
                },
            )
            success = res.status_code in (200, 201)
            if not success:
                print(f"[Resend] Error {res.status_code}: {res.text}")
            return success
    except Exception as e:
        print(f"[Resend] Exception: {e}")
        return False


async def _send_sms_twilio(phone: str, temp_password: str) -> bool:
    """Send SMS via Twilio."""
    if not TWILIO_SID or not TWILIO_TOKEN or not TWILIO_SMS_FROM:
        print(f"[DEV - no Twilio SMS config] SMS to {phone}: {temp_password}")
        return True  # dev mode

    ph = phone.strip().replace(" ", "").replace("-", "")
    if not ph.startswith("+"):
        ph = "+" + ph

    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(
            body=(
                f"CARSTRIMS: Your new temporary password is:\n\n"
                f"{temp_password}\n\n"
                f"Change it immediately after login from Settings.\n"
                f"Did not request this? Email support@carstrims.com"
            ),
            from_=TWILIO_SMS_FROM,
            to=ph,
        )
        return True
    except Exception as e:
        print(f"[Twilio SMS] Error: {e}")
        return False


async def _send_whatsapp_twilio(phone: str, temp_password: str, name: str) -> bool:
    """Send WhatsApp message via Twilio Sandbox."""
    if not TWILIO_SID or not TWILIO_TOKEN:
        print(f"[DEV - no Twilio config] WhatsApp to {phone}: {temp_password}")
        return True  # dev mode

    ph = phone.strip().replace(" ", "").replace("-", "")
    if not ph.startswith("+"):
        ph = "+" + ph
    wa_to = f"whatsapp:{ph}"

    try:
        from twilio.rest import Client
        client = Client(TWILIO_SID, TWILIO_TOKEN)
        client.messages.create(
            body=(
                f"*CARSTRIMS*\n\n"
                f"Hi {name}, your new temporary password is:\n\n"
                f"*{temp_password}*\n\n"
                f"Please log in and change it immediately from Settings.\n\n"
                f"Did not request this? Contact support@carstrims.com"
            ),
            from_=TWILIO_WA_FROM,
            to=wa_to,
        )
        return True
    except Exception as e:
        print(f"[Twilio WhatsApp] Error: {e}")
        return False


async def _notify_admin(db, user: dict, temp_password: str):
    admins = await db["users"].find({"role": "SYSTEM_ADMIN"}).to_list(5)
    for admin in admins:
        await db["notifications"].insert_one({
            "receiverId": str(admin["_id"]),
            "type": "general",
            "title": "Password Recovery Request",
            "message": (
                f"{user.get('fullName', 'A user')} ({user['email']}) requested "
                f"password recovery via Admin Support. Temp password set to: {temp_password}"
            ),
            "isRead": False,
            "createdAt": datetime.utcnow(),
        })
