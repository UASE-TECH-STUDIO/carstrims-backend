import random
import string
from datetime import datetime
from bson import ObjectId
from app.database.connection import get_db
from app.auth.password import hash_password


async def forgot_password(email: str) -> dict:
    db = get_db()
    user = await db["users"].find_one({"email": email})

    if not user:
        return {"message": "If this email is registered, a new password has been sent to it."}

    new_password = "Reset@" + "".join(
        random.choices(string.ascii_letters + string.digits, k=8)
    )

    await db["users"].update_one(
        {"_id": user["_id"]},
        {"$set": {
            "passwordHash": hash_password(new_password),
            "updatedAt": datetime.utcnow(),
        }},
    )

    await db["notifications"].insert_one({
        "receiverId": str(user["_id"]),
        "type": "general",
        "title": "Password Reset",
        "message": f"Your password has been reset. New password: {new_password} — Please change it after login.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    return {
        "message": "Password reset successfully. Check your notifications for the new password.",
        "newPassword": new_password,
        "note": "In production this would be sent via email",
    }


async def admin_reset_user_password(user_id: str) -> dict:
    db = get_db()
    new_password = "Reset@" + "".join(
        random.choices(string.digits + string.ascii_letters, k=8)
    )
    await db["users"].update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"passwordHash": hash_password(new_password), "updatedAt": datetime.utcnow()}},
    )
    return {"message": "Password reset", "newPassword": new_password}
