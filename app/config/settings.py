import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Email via Resend
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    RESEND_FROM: str = os.getenv("RESEND_FROM", "CARSTRIMS <onboarding@resend.dev>")

    # Legacy SMTP (not used if Resend is set)
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    FROM_EMAIL: str = ""

    # Twilio SMS
    TWILIO_ACCOUNT_SID: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.getenv("TWILIO_PHONE_NUMBER", "")

    # Twilio WhatsApp Sandbox
    TWILIO_WA_FROM: str = os.getenv("TWILIO_WA_FROM", "whatsapp:+14155238886")
    TWILIO_WA_JOIN: str = os.getenv("TWILIO_WA_JOIN", "join ants-whistle")

    # App
    APP_NAME: str = "CARSTRIMS"
    DEBUG: bool = False
    FRONTEND_URL: str = "https://carstrims-app.vercel.app"

    # MongoDB
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    DB_NAME: str = os.getenv("DB_NAME", "car_dealer_db")

    # JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "carstrims-super-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200  # 30 days - users stay logged in permanently
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY: str = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET: str = os.getenv("CLOUDINARY_API_SECRET", "")

    # Web Push (VAPID)
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
