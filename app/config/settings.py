import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Email (SMTP) ──
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""
    FROM_EMAIL: str = ""

    # ── Twilio (SMS + WhatsApp) ──
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    TWILIO_WHATSAPP_FROM: str = "whatsapp:+14155238886"

    APP_NAME: str = "CARSTRIMS"
    DEBUG: bool = False
    FRONTEND_URL: str = "https://carstrims-app.vercel.app"

    # MongoDB
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    DB_NAME: str = os.getenv("DB_NAME", "car_dealer_db")

    # JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "carstrims-super-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY: str = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET: str = os.getenv("CLOUDINARY_API_SECRET", "")

        # ── Web Push (VAPID) ──
    VAPID_PUBLIC_KEY: str = ""
    VAPID_PRIVATE_KEY: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()


