"""
Forgot password service — generates a temp password and delivers it via
SMS (Twilio), WhatsApp (Twilio), Email (SMTP/SendGrid), or Admin message.
"""
import random, string
from datetime import datetime
from fastapi import HTTPException
from app.database.connection import get_db
from app.auth.password import hash_password
from app.config.settings import settings


def _gen_temp_password(length=10) -> str:
    chars = string.ascii_letters + string.digits
    return "Temp@" + "".join(random.choices(chars, k=length))


async def get_recovery_options(email: str) -> dict:
    db = get_db()
    user = await db["users"].find_one({"email": email.lower().strip()})
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email address.")

    options = []

    if user.get("phone"):
        masked_phone = user["phone"][:4] + "****" + user["phone"][-3:] if len(user["phone"]) > 7 else user["phone"]
        options.append({
            "type": "sms",
            "label": "Send via SMS",
            "masked": f"Send a new password by text message to {masked_phone}",
        })

    if user.get("whatsapp"):
        masked_wa = user["whatsapp"][:4] + "****" + user["whatsapp"][-3:] if len(user["whatsapp"]) > 7 else user["whatsapp"]
        options.append({
            "type": "whatsapp",
            "label": "Send via WhatsApp",
            "masked": f"Send a new password to WhatsApp {masked_wa}",
        })

    if user.get("email"):
        parts = user["email"].split("@")
        masked_email = parts[0][:2] + "***@" + parts[1] if len(parts) > 1 else user["email"]
        options.append({
            "type": "email",
            "label": "Send to Email",
            "masked": f"Send a new password to {masked_email}",
        })

    # Always add admin support option
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
        {"$set": {
            "passwordHash": hashed,
            "tempPassword": True,
            "updatedAt": datetime.utcnow(),
        }},
    )

    if method == "email":
        await _send_email(user["email"], user.get("fullName", "User"), temp_password)

    elif method == "sms":
        phone = user.get("phone")
        if not phone:
            raise HTTPException(status_code=400, detail="No phone number on this account. Try Email or Admin Support.")
        await _send_sms(phone, temp_password)

    elif method == "whatsapp":
        wa = user.get("whatsapp") or user.get("phone")
        if not wa:
            raise HTTPException(status_code=400, detail="No WhatsApp number on this account. Try Email or Admin Support.")
        await _send_whatsapp(wa, temp_password, user.get("fullName", "User"))

    elif method == "admin_message":
        await _notify_admin(db, user, temp_password)

    else:
        raise HTTPException(status_code=400, detail=f"Unknown recovery method: {method}")

    return {"message": f"Recovery sent via {method}"}


async def _send_email(to_email: str, name: str, temp_password: str):
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        smtp_host = getattr(settings, "SMTP_HOST", None)
        smtp_port = int(getattr(settings, "SMTP_PORT", 587))
        smtp_user = getattr(settings, "SMTP_USER", None)
        smtp_pass = getattr(settings, "SMTP_PASS", None)
        from_email = getattr(settings, "FROM_EMAIL", smtp_user)

        if not smtp_host or not smtp_user:
            # Fallback: just log (dev mode)
            print(f"[DEV] Password reset email → {to_email}: temp={temp_password}")
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "CARSTRIMS — Your New Temporary Password"
        msg["From"] = f"CARSTRIMS <{from_email}>"
        msg["To"] = to_email

        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:20px">
          <h2 style="color:#F47B20;font-family:Georgia,serif;letter-spacing:0.1em">CARSTRIMS</h2>
          <p>Hi {name},</p>
          <p>Your account password has been reset. Use the temporary password below to log in:</p>
          <div style="background:#F5F5F5;border:2px solid #F47B20;border-radius:8px;padding:20px;text-align:center;margin:20px 0">
            <span style="font-size:1.5rem;font-weight:bold;letter-spacing:0.1em;color:#1A1A1A">{temp_password}</span>
          </div>
          <p style="color:#DC2626"><strong>⚠ Please change this password immediately after logging in from your Settings page.</strong></p>
          <p style="color:#737373;font-size:0.85rem">If you did not request this, contact support@carstrims.com immediately.</p>
          <p style="color:#A3A3A3;font-size:0.75rem;margin-top:2rem">CARSTRIMS · Built by UASE TECH STUDIO</p>
        </div>
        """

        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, to_email, msg.as_string())

    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        raise HTTPException(status_code=500, detail=f"Could not send email: {str(e)}")


async def _send_sms(phone: str, temp_password: str):
    try:
        account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
        auth_token  = getattr(settings, "TWILIO_AUTH_TOKEN", None)
        from_number = getattr(settings, "TWILIO_PHONE_NUMBER", None)

        if not account_sid or not auth_token or not from_number:
            print(f"[DEV] SMS → {phone}: temp={temp_password}")
            return

        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        client.messages.create(
            body=f"CARSTRIMS: Your new temporary password is: {temp_password}\nChange it immediately after login. If you did not request this, contact support.",
            from_=from_number,
            to=phone,
        )
    except Exception as e:
        print(f"[SMS ERROR] {e}")
        raise HTTPException(status_code=500, detail=f"Could not send SMS: {str(e)}")


async def _send_whatsapp(phone: str, temp_password: str, name: str):
    try:
        account_sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
        auth_token  = getattr(settings, "TWILIO_AUTH_TOKEN", None)
        wa_from     = getattr(settings, "TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

        if not account_sid or not auth_token:
            print(f"[DEV] WhatsApp → {phone}: temp={temp_password}")
            return

        # Normalize phone
        wa_to = phone.strip()
        if not wa_to.startswith("whatsapp:"):
            if not wa_to.startswith("+"):
                wa_to = "+" + wa_to
            wa_to = f"whatsapp:{wa_to}"

        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        client.messages.create(
            body=f"*CARSTRIMS* 🚗\n\nHi {name}, your new temporary password is:\n\n*{temp_password}*\n\nPlease log in and change it immediately from Settings.\n\nIf you did not request this, contact support@carstrims.com",
            from_=wa_from,
            to=wa_to,
        )
    except Exception as e:
        print(f"[WHATSAPP ERROR] {e}")
        raise HTTPException(status_code=500, detail=f"Could not send WhatsApp message: {str(e)}")


async def _notify_admin(db, user: dict, temp_password: str):
    admins = await db["users"].find({"role": "SYSTEM_ADMIN"}).to_list(5)
    for admin in admins:
        await db["notifications"].insert_one({
            "receiverId": str(admin["_id"]),
            "type": "general",
            "title": "Password Recovery Request",
            "message": f"{user.get('fullName','A user')} ({user['email']}) requested password recovery via admin support. Temp password set: {temp_password}",
            "isRead": False,
            "createdAt": datetime.utcnow(),
        })
