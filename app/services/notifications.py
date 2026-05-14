"""
CARSTRIMS Notification Service
Handles: Email (Resend), WhatsApp (Twilio Sandbox), SMS (Twilio)
"""
import os
import httpx
from datetime import datetime
from typing import Optional

import os

# ── Resend Email Config ────────────────────────────────────────
# No keys here! They stay in the .env file.
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM    = os.getenv("RESEND_FROM", "CARSTRIMS <onboarding@resend.dev>")

# ── Twilio WhatsApp Config ─────────────────────────────────────
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WA_FROM     = os.getenv("TWILIO_WA_FROM", "whatsapp:+14155238886")
TWILIO_WA_JOIN     = os.getenv("TWILIO_WA_JOIN", "join ants-whistle")


# ── EMAIL via Resend ──────────────────────────────────────────
async def send_email(to: str, subject: str, html: str) -> bool:
    """Send email via Resend API."""
    if not to or "@" not in to:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": RESEND_FROM,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
            return res.status_code in (200, 201)
    except Exception as e:
        print(f"[Email] Error sending to {to}: {e}")
        return False


# ── WHATSAPP via Twilio Sandbox ───────────────────────────────
async def send_whatsapp(to_phone: str, message: str) -> bool:
    """
    Send WhatsApp message via Twilio Sandbox.
    NOTE: Recipient must first join sandbox by sending
    'join ants-whistle' to +1 415 523 8886 on WhatsApp.
    to_phone: international format e.g. +2348146550674
    """
    if not to_phone:
        return False
    # Normalize phone number
    phone = to_phone.strip().replace(" ", "").replace("-", "")
    if not phone.startswith("+"):
        phone = "+" + phone
    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            from_=TWILIO_WA_FROM,
            to=f"whatsapp:{phone}",
            body=message,
        )
        return True
    except Exception as e:
        print(f"[WhatsApp] Error sending to {phone}: {e}")
        return False


# ── SMS via Twilio ────────────────────────────────────────────
async def send_sms(to_phone: str, message: str) -> bool:
    """Send SMS via Twilio. Requires a paid Twilio number."""
    twilio_sms_from = os.getenv("TWILIO_SMS_FROM", "")
    if not twilio_sms_from or not to_phone:
        return False
    phone = to_phone.strip().replace(" ", "")
    if not phone.startswith("+"):
        phone = "+" + phone
    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(from_=twilio_sms_from, to=phone, body=message)
        return True
    except Exception as e:
        print(f"[SMS] Error sending to {phone}: {e}")
        return False


# ── EMAIL TEMPLATES ───────────────────────────────────────────
def email_base(title: str, body: str, footer: str = "") -> str:
    """Base HTML email template."""
    return f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#F5F5F5;font-family:Arial,sans-serif">
  <div style="max-width:560px;margin:2rem auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08)">
    <div style="background:#1A1A1A;padding:1.5rem 2rem">
      <h1 style="color:#F47B20;margin:0;font-size:1.5rem;letter-spacing:0.15em">CARSTRIMS</h1>
    </div>
    <div style="padding:2rem">
      <h2 style="color:#1A1A1A;margin-top:0">{title}</h2>
      {body}
    </div>
    <div style="background:#F5F5F5;padding:1rem 2rem;font-size:0.75rem;color:#888;text-align:center">
      {footer or "CARSTRIMS · Built by UASE TECH STUDIO · Nigeria's Premier Vehicle Marketplace"}
    </div>
  </div>
</body>
</html>
"""


# ── PRE-BUILT NOTIFICATION FUNCTIONS ─────────────────────────

async def notify_registration(user: dict):
    """Send welcome notification after registration."""
    name    = user.get("fullName", "there")
    email   = user.get("email", "")
    phone   = user.get("whatsapp") or user.get("phone", "")
    role    = user.get("role", "PUBLIC_USER")

    role_msg = {
        "DEALER_ADMIN": "your dealership account",
        "PARTNER_USER": "your partner account",
        "PUBLIC_USER":  "your buyer account",
    }.get(role, "your account")

    # Email
    html = email_base(
        f"Welcome to CARSTRIMS, {name}! 🎉",
        f"""
        <p style="color:#525252;line-height:1.6">
          Thank you for joining CARSTRIMS — Nigeria's premier vehicle marketplace.
          We have successfully created <strong>{role_msg}</strong>.
        </p>
        <div style="background:#FFF7ED;border-left:4px solid #F47B20;padding:1rem;margin:1.5rem 0;border-radius:0 8px 8px 0">
          <p style="margin:0;color:#C4621A;font-size:0.875rem">
            {"After completing your dealership setup, your account will be reviewed and approved within 24 hours." if role == "DEALER_ADMIN" else "You can now browse vehicles, save favourites, and message dealers directly."}
          </p>
        </div>
        <a href="https://carstrims-app.vercel.app/login"
          style="display:inline-block;background:#F47B20;color:#fff;text-decoration:none;padding:0.875rem 2rem;border-radius:8px;font-weight:bold;margin-top:0.5rem">
          Go to Dashboard →
        </a>
        """,
    )
    await send_email(email, f"Welcome to CARSTRIMS, {name}!", html)

    # WhatsApp
    wa_msg = (
        f"👋 Welcome to CARSTRIMS, {name}!\n\n"
        f"Your {role_msg} has been created successfully.\n\n"
        f"{'Complete your dealership setup at: https://carstrims-app.vercel.app/dashboard/dealer/setup' if role == 'DEALER_ADMIN' else 'Start browsing vehicles at: https://carstrims-app.vercel.app/feed'}\n\n"
        f"_CARSTRIMS — Built by UASE TECH STUDIO_"
    )
    await send_whatsapp(phone, wa_msg)


async def notify_dealer_approved(dealer: dict, user: dict):
    """Send approval notification to dealer."""
    name  = user.get("fullName", "Dealer")
    email = user.get("email", "")
    phone = user.get("whatsapp") or user.get("phone", "")
    company = dealer.get("companyName", "Your dealership")

    html = email_base(
        "Your Dealership Has Been Approved ✅",
        f"""
        <p style="color:#525252;line-height:1.6">
          Great news, {name}! <strong>{company}</strong> has been approved on CARSTRIMS.
          Your listings are now visible to all buyers on the platform.
        </p>
        <div style="background:#F0FDF4;border-left:4px solid #16A34A;padding:1rem;margin:1.5rem 0;border-radius:0 8px 8px 0">
          <p style="margin:0;color:#15803D">✅ Account Status: <strong>Approved & Active</strong></p>
        </div>
        <a href="https://carstrims-app.vercel.app/dashboard/dealer"
          style="display:inline-block;background:#F47B20;color:#fff;text-decoration:none;padding:0.875rem 2rem;border-radius:8px;font-weight:bold">
          Go to Your Dashboard →
        </a>
        """,
    )
    await send_email(email, f"🎉 {company} is Approved on CARSTRIMS!", html)

    wa_msg = (
        f"✅ *CARSTRIMS Approval Notice*\n\n"
        f"Hello {name}!\n\n"
        f"*{company}* has been approved on CARSTRIMS.\n\n"
        f"Your vehicle listings are now live on the platform.\n\n"
        f"👉 Dashboard: https://carstrims-app.vercel.app/dashboard/dealer\n\n"
        f"_CARSTRIMS — Built by UASE TECH STUDIO_"
    )
    await send_whatsapp(phone, wa_msg)


async def notify_dealer_rejected(dealer: dict, user: dict, reason: str = ""):
    """Send rejection notification."""
    name    = user.get("fullName", "Dealer")
    email   = user.get("email", "")
    phone   = user.get("whatsapp") or user.get("phone", "")
    company = dealer.get("companyName", "Your dealership")

    html = email_base(
        "Application Update — CARSTRIMS",
        f"""
        <p style="color:#525252;line-height:1.6">
          Hello {name}, we have reviewed your application for <strong>{company}</strong>.
        </p>
        <div style="background:#FEF2F2;border-left:4px solid #DC2626;padding:1rem;margin:1.5rem 0;border-radius:0 8px 8px 0">
          <p style="margin:0;color:#DC2626"><strong>Status: Not Approved</strong></p>
          {f'<p style="margin:0.5rem 0 0;color:#737373;font-size:0.875rem">{reason}</p>' if reason else ""}
        </div>
        <p style="color:#525252;font-size:0.875rem">
          You may re-apply after addressing the issues noted above.
          Contact <a href="mailto:support@carstrims.com">support@carstrims.com</a> for assistance.
        </p>
        """,
    )
    await send_email(email, "CARSTRIMS — Application Update", html)

    wa_msg = (
        f"⚠️ *CARSTRIMS Application Update*\n\n"
        f"Hello {name}, your application for *{company}* was not approved.\n\n"
        f"{f'Reason: {reason}' if reason else ''}\n\n"
        f"Contact support@carstrims.com for assistance.\n\n"
        f"_CARSTRIMS — Built by UASE TECH STUDIO_"
    )
    await send_whatsapp(phone, wa_msg)


async def notify_password_reset(user: dict, new_password: str, method: str = "notification"):
    """Send password reset notification."""
    name  = user.get("fullName", "User")
    email = user.get("email", "")
    phone = user.get("whatsapp") or user.get("phone", "")

    html = email_base(
        "Your Password Has Been Reset",
        f"""
        <p style="color:#525252;line-height:1.6">Hello {name}, your CARSTRIMS password has been reset.</p>
        <div style="background:#F5F5F5;border:1px solid #E5E5E5;border-radius:8px;padding:1.25rem;margin:1.5rem 0;text-align:center">
          <p style="margin:0;font-size:0.8rem;color:#888;text-transform:uppercase;letter-spacing:0.1em">New Temporary Password</p>
          <p style="margin:0.5rem 0 0;font-size:1.5rem;font-family:monospace;color:#1A1A1A;font-weight:bold">{new_password}</p>
        </div>
        <p style="color:#DC2626;font-size:0.875rem">⚠️ Please log in and change this password immediately from your Settings page.</p>
        <a href="https://carstrims-app.vercel.app/login"
          style="display:inline-block;background:#F47B20;color:#fff;text-decoration:none;padding:0.875rem 2rem;border-radius:8px;font-weight:bold">
          Login Now →
        </a>
        """,
    )
    await send_email(email, "CARSTRIMS — Password Reset", html)

    wa_msg = (
        f"🔑 *CARSTRIMS Password Reset*\n\n"
        f"Hello {name}!\n\n"
        f"Your temporary password is:\n*{new_password}*\n\n"
        f"⚠️ Please login and change it immediately from Settings.\n\n"
        f"👉 https://carstrims-app.vercel.app/login\n\n"
        f"_CARSTRIMS — Built by UASE TECH STUDIO_"
    )
    await send_whatsapp(phone, wa_msg)


async def send_broadcast_email(recipients: list, subject: str, message: str, title: str = ""):
    """
    Send broadcast email to multiple recipients.
    recipients: list of {"email": str, "fullName": str}
    """
    html_body = f"""
        <p style="color:#525252;line-height:1.7;font-size:0.95rem">{message.replace(chr(10), '<br>')}</p>
    """
    html = email_base(title or subject, html_body)

    # Send to each recipient individually (personalized)
    sent = 0
    for r in recipients:
        personalized = html.replace("</h2>", f"</h2><p style='color:#888;font-size:0.8rem'>Hi {r.get('fullName','there')},</p>")
        ok = await send_email(r.get("email", ""), subject, personalized)
        if ok:
            sent += 1
    return sent


async def notify_new_message(receiver: dict, sender_name: str, message_preview: str):
    """Notify user of a new message."""
    phone = receiver.get("whatsapp") or receiver.get("phone", "")
    name  = receiver.get("fullName", "User")

    wa_msg = (
        f"💬 *New message on CARSTRIMS*\n\n"
        f"Hello {name}!\n"
        f"*{sender_name}* sent you a message:\n"
        f"_{message_preview[:80]}{'...' if len(message_preview) > 80 else ''}_\n\n"
        f"👉 Reply at: https://carstrims-app.vercel.app/dashboard\n\n"
        f"_CARSTRIMS_"
    )
    await send_whatsapp(phone, wa_msg)


async def notify_new_car_posted(followers: list, dealer_name: str, car: dict, car_url: str):
    """Notify dealer followers when a new vehicle is posted."""
    car_title = f"{car.get('brand','')} {car.get('model','')} {car.get('year','')}"
    price     = f"₦{car.get('sellingPrice',0):,}"

    for follower in followers:
        email = follower.get("email", "")
        phone = follower.get("whatsapp") or follower.get("phone", "")
        name  = follower.get("fullName", "there")

        if email:
            html = email_base(
                f"New Vehicle from {dealer_name}",
                f"""
                <p style="color:#525252">Hello {name}, <strong>{dealer_name}</strong> just listed a new vehicle!</p>
                <div style="background:#F5F5F5;border-radius:8px;padding:1.25rem;margin:1rem 0">
                  <h3 style="margin:0;color:#1A1A1A">{car_title}</h3>
                  <p style="color:#F47B20;font-size:1.25rem;font-weight:bold;margin:0.5rem 0">{price}</p>
                  <p style="color:#737373;font-size:0.85rem;margin:0">{car.get('color','')} · {car.get('transmission','')} · {car.get('condition','')}</p>
                </div>
                <a href="{car_url}" style="display:inline-block;background:#F47B20;color:#fff;text-decoration:none;padding:0.875rem 2rem;border-radius:8px;font-weight:bold">View Vehicle →</a>
                """,
            )
            await send_email(email, f"New Vehicle from {dealer_name} — CARSTRIMS", html)

        if phone:
            await send_whatsapp(phone, (
                f"🚗 *New Vehicle Alert — CARSTRIMS*\n\n"
                f"Hello {name}!\n\n"
                f"*{dealer_name}* just listed:\n"
                f"*{car_title}*\n"
                f"Price: *{price}*\n\n"
                f"👉 View it: {car_url}\n\n"
                f"_CARSTRIMS_"
            ))
