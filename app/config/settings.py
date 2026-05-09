import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "CARSTRIMS"
    DEBUG: bool = False
    FRONTEND_URL: str = "https://carstrims.vercel.app"

    # MongoDB
    MONGODB_URL: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    DATABASE_NAME: str = os.getenv("DATABASE_NAME", "car_dealer_db")

    # JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "carstrims-super-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY: str = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET: str = os.getenv("CLOUDINARY_API_SECRET", "")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
