from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc
from app.auth.password import hash_password
import random
import string


def generate_staff_id():
    return "STF-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


async def create_staff(dealer_id: str, data: dict) -> dict:
    db = get_db()

    existing_email = await db["users"].find_one({"email": data.get("email")})
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")

    # BUG FIX: the schema documented "username: auto-generated if not
    # provided" but that generation was never implemented — every staff
    # account was being stored with username=None, so the very next
    # staff account created ANYWHERE on the platform would collide with
    # that None value and fail with a confusing "Username already taken"
    # error (confusing because staff are never asked to enter a username
    # at all). This generates a real, unique username as the schema
    # always intended.
    username = data.get("username")
    if not username:
        base = "".join(c for c in (data.get("fullName") or "staff").lower() if c.isalnum()) or "staff"
        base = base[:20]
        username = base
        attempt = 0
        while await db["users"].find_one({"username": username}):
            attempt += 1
            suffix = "".join(random.choices(string.digits, k=4))
            username = f"{base}{suffix}"
            if attempt > 20:  # extremely unlikely, but never loop forever
                username = f"{base}{generate_staff_id()[-6:]}"
                break
    else:
        existing_username = await db["users"].find_one({"username": username})
        if existing_username:
            raise HTTPException(status_code=400, detail="Username already taken")

    password = data.get("password", "Staff@1234")

    user_doc = {
        "fullName": data.get("fullName"),
        "username": username,
        "email": data.get("email"),
        "phone": data.get("phone"),
        "whatsapp": data.get("whatsapp"),
        "address": data.get("address"),
        "role": "DEALER_STAFF",
        "passwordHash": hash_password(password),
        "status": "active",
        "dealerId": dealer_id,
        "profilePicture": None,
        "isEmailVerified": False,
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
        "lastLogin": None,
    }

    user_result = await db["users"].insert_one(user_doc)
    user_id = str(user_result.inserted_id)

    staff_doc = {
        "staffId": generate_staff_id(),
        "dealerId": dealer_id,
        "userId": user_id,
        "fullName": data.get("fullName"),
        "email": data.get("email"),
        "phone": data.get("phone"),
        "whatsapp": data.get("whatsapp"),
        "address": data.get("address"),
        "position": data.get("position", "Staff"),
        "profilePicture": None,
        "permissions": data.get("permissions", []),
        "status": "active",
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
        "lastActive": None,
    }

    result = await db["staff_accounts"].insert_one(staff_doc)
    staff_doc["_id"] = result.inserted_id

    return {**serialize_doc(staff_doc), "tempPassword": password}


async def get_dealer_staff(
    dealer_id: str,
    search: str = None,
    skip: int = 0,
    limit: int = 20,
) -> dict:
    db = get_db()

    query = {"dealerId": dealer_id}
    if search:
        query["$or"] = [
            {"fullName": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"position": {"$regex": search, "$options": "i"}},
            {"staffId": {"$regex": search, "$options": "i"}},
        ]

    total = await db["staff_accounts"].count_documents(query)
    staff = await db["staff_accounts"].find(query).sort(
        "createdAt", -1
    ).skip(skip).limit(limit).to_list(limit)

    return {
        "total": total,
        "staff": [serialize_doc(s) for s in staff],
        "skip": skip,
        "limit": limit,
    }


async def get_staff_by_id(staff_id: str, dealer_id: str) -> dict:
    db = get_db()

    if ObjectId.is_valid(staff_id):
        query = {"_id": ObjectId(staff_id), "dealerId": dealer_id}
    else:
        query = {"staffId": staff_id, "dealerId": dealer_id}

    staff = await db["staff_accounts"].find_one(query)
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")
    return serialize_doc(staff)


async def update_staff(staff_id: str, dealer_id: str, data: dict) -> dict:
    db = get_db()

    if ObjectId.is_valid(staff_id):
        query = {"_id": ObjectId(staff_id), "dealerId": dealer_id}
    else:
        query = {"staffId": staff_id, "dealerId": dealer_id}

    staff = await db["staff_accounts"].find_one(query)
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    data.pop("_id", None)
    data.pop("dealerId", None)
    data.pop("userId", None)
    data["updatedAt"] = datetime.utcnow()

    await db["staff_accounts"].update_one({"_id": staff["_id"]}, {"$set": data})

    if "fullName" in data or "phone" in data:
        user_update = {}
        if "fullName" in data:
            user_update["fullName"] = data["fullName"]
        if "phone" in data:
            user_update["phone"] = data["phone"]
        if user_update:
            await db["users"].update_one(
                {"_id": ObjectId(staff["userId"])},
                {"$set": {**user_update, "updatedAt": datetime.utcnow()}},
            )

    return await get_staff_by_id(str(staff["_id"]), dealer_id)


async def suspend_staff(staff_id: str, dealer_id: str) -> dict:
    db = get_db()

    if ObjectId.is_valid(staff_id):
        query = {"_id": ObjectId(staff_id), "dealerId": dealer_id}
    else:
        query = {"staffId": staff_id, "dealerId": dealer_id}

    staff = await db["staff_accounts"].find_one(query)
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    new_status = "active" if staff["status"] == "suspended" else "suspended"

    await db["staff_accounts"].update_one(
        {"_id": staff["_id"]},
        {"$set": {"status": new_status, "updatedAt": datetime.utcnow()}},
    )
    await db["users"].update_one(
        {"_id": ObjectId(staff["userId"])},
        {"$set": {"status": new_status, "updatedAt": datetime.utcnow()}},
    )

    return {"message": f"Staff {new_status}", "status": new_status}


async def delete_staff(staff_id: str, dealer_id: str) -> dict:
    db = get_db()

    if ObjectId.is_valid(staff_id):
        query = {"_id": ObjectId(staff_id), "dealerId": dealer_id}
    else:
        query = {"staffId": staff_id, "dealerId": dealer_id}

    staff = await db["staff_accounts"].find_one(query)
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    await db["staff_accounts"].delete_one({"_id": staff["_id"]})
    await db["users"].update_one(
        {"_id": ObjectId(staff["userId"])},
        {"$set": {"status": "deleted", "updatedAt": datetime.utcnow()}},
    )

    return {"message": "Staff removed successfully"}


async def update_staff_permissions(
    staff_id: str, dealer_id: str, permissions: list
) -> dict:
    db = get_db()

    if ObjectId.is_valid(staff_id):
        query = {"_id": ObjectId(staff_id), "dealerId": dealer_id}
    else:
        query = {"staffId": staff_id, "dealerId": dealer_id}

    staff = await db["staff_accounts"].find_one(query)
    if not staff:
        raise HTTPException(status_code=404, detail="Staff not found")

    await db["staff_accounts"].update_one(
        {"_id": staff["_id"]},
        {"$set": {"permissions": permissions, "updatedAt": datetime.utcnow()}},
    )

    return {"message": "Permissions updated", "permissions": permissions}


async def update_staff_profile(staff_id: str, dealer_id: str, data: dict) -> dict:
    """Full staff profile update including position, phone, address"""
    db = get_db()

    if ObjectId.is_valid(staff_id):
        query = {"_id": ObjectId(staff_id), "dealerId": dealer_id}
    else:
        query = {"staffId": staff_id, "dealerId": dealer_id}

    staff = await db["staff_accounts"].find_one(query)
    if not staff:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Staff not found")

    allowed = ["fullName", "phone", "whatsapp", "address", "position"]
    update = {k: v for k, v in data.items() if k in allowed and v is not None}
    update["updatedAt"] = datetime.utcnow()

    await db["staff_accounts"].update_one({"_id": staff["_id"]}, {"$set": update})

    if "fullName" in update or "phone" in update:
        user_update = {}
        if "fullName" in update: user_update["fullName"] = update["fullName"]
        if "phone" in update: user_update["phone"] = update["phone"]
        if user_update:
            await db["users"].update_one(
                {"_id": ObjectId(staff["userId"])},
                {"$set": {**user_update, "updatedAt": datetime.utcnow()}},
            )

    updated = await db["staff_accounts"].find_one({"_id": staff["_id"]})
    return serialize_doc(updated)
