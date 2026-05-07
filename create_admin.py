import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import bcrypt
import os
from dotenv import load_dotenv

load_dotenv()

MONGODB_URL = os.getenv("MONGODB_URL")
DB_NAME = os.getenv("DB_NAME", "car_dealer_db")


async def create_super_admin():
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[DB_NAME]

    existing = await db["users"].find_one({"role": "SYSTEM_ADMIN"})
    if existing:
        print("Super admin already exists:", existing["email"])
        client.close()
        return

    password = "Admin@12345"
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    from datetime import datetime
    admin = {
        "fullName": "System Administrator",
        "username": "superadmin",
        "email": "admin@cardealerapp.com",
        "phone": "00000000000",
        "role": "SYSTEM_ADMIN",
        "passwordHash": hashed,
        "status": "active",
        "dealerId": None,
        "profilePicture": None,
        "isEmailVerified": True,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
        "lastLogin": None,
    }

    result = await db["users"].insert_one(admin)
    print(f"Super admin created successfully!")
    print(f"Email: admin@cardealerapp.com")
    print(f"Password: Admin@12345")
    print(f"ID: {result.inserted_id}")
    print("IMPORTANT: Change this password after first login!")
    client.close()


asyncio.run(create_super_admin())
