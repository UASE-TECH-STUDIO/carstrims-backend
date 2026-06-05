from fastapi import APIRouter, Depends, Query, Body
from typing import Optional, List
from pydantic import BaseModel
from app.auth.dependencies import get_current_user
from app.modules.dealers.service import serialize_doc
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime
import random, string


class StaffCreateRequest(BaseModel):
    fullName: str
    email: str
    phone: str
    position: str
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    password: Optional[str] = "Staff@1234"
    permissions: List[str] = []
    username: Optional[str] = None  # auto-generated from email


class StaffUpdateRequest(BaseModel):
    fullName: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    address: Optional[str] = None
    position: Optional[str] = None


class StaffPermissionsRequest(BaseModel):
    permissions: List[str]


def gen_staff_id():
    return "STF-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


router = APIRouter(prefix="/api/v1/staff", tags=["Staff"])


@router.get("/me")
async def get_my_staff_profile(current_user: dict = Depends(get_current_user)):
    db = get_db()
    staff = await db["staff_accounts"].find_one({"userId": str(current_user["_id"])})
    if not staff:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Staff profile not found")
    return serialize_doc(staff)


@router.patch("/me/profile")
async def update_my_profile(
    data: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    staff = await db["staff_accounts"].find_one({"userId": str(current_user["_id"])})
    if not staff:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Staff not found")

    allowed = ["fullName", "phone", "whatsapp", "address"]
    update = {k: v for k, v in data.items() if k in allowed and v is not None}
    update["updatedAt"] = datetime.utcnow()

    await db["staff_accounts"].update_one({"_id": staff["_id"]}, {"$set": update})

    if "fullName" in update or "phone" in update:
        user_update = {}
        if "fullName" in update:
            user_update["fullName"] = update["fullName"]
        if "phone" in update:
            user_update["phone"] = update["phone"]
        await db["users"].update_one(
            {"_id": ObjectId(str(current_user["_id"]))},
            {"$set": {**user_update, "updatedAt": datetime.utcnow()}},
        )

    updated = await db["staff_accounts"].find_one({"_id": staff["_id"]})
    return serialize_doc(updated)


@router.get("/me/dealer")
async def get_my_dealer_info(current_user: dict = Depends(get_current_user)):
    """Staff fetches their own dealer's info"""
    db = get_db()
    staff = await db["staff_accounts"].find_one({"userId": str(current_user["_id"])})
    if not staff:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Staff not found")
    dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(staff["dealerId"])})
    return serialize_doc(dealer) if dealer else {}


@router.post("/")
async def create_staff(data: StaffCreateRequest, current_user: dict = Depends(get_current_user)):
    db = get_db()
    from app.modules.dealers.service import get_dealer_by_user_id
    from app.auth.password import hash_password

    # Allow dealer admin OR staff with create_staff permission
    staff_self = await db["staff_accounts"].find_one({"userId": str(current_user["_id"])})
    dealer = None

    if current_user["role"] == "DEALER_ADMIN":
        dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    elif staff_self and "create_staff" in (staff_self.get("permissions") or []):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(staff_self["dealerId"])})
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="No permission to create staff")

    existing = await db["users"].find_one({"email": data.email})
    if existing:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Email already registered")

    temp_password = data.password or "Staff@" + "".join(random.choices(string.digits, k=6))

    # Auto-generate username from email if not provided
    auto_username = data.username or data.email.split("@")[0]

    user_doc = {
        "fullName": data.fullName,
        "username": auto_username,
        "email": data.email,
        "passwordHash": hash_password(temp_password),
        "phone": data.phone,
        "whatsapp": data.whatsapp,
        "address": data.address,
        "role": "DEALER_STAFF",
        "status": "active",
        "dealerId": dealer["_id"],
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    user_result = await db["users"].insert_one(user_doc)

    staff_doc = {
        "staffId": gen_staff_id(),
        "userId": str(user_result.inserted_id),
        "dealerId": dealer["_id"],
        "fullName": data.fullName,
        "email": data.email,
        "phone": data.phone,
        "whatsapp": data.whatsapp,
        "address": data.address,
        "position": data.position,
        "permissions": data.permissions,
        "status": "active",
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow(),
    }

    await db["staff_accounts"].insert_one(staff_doc)

    return {
        **serialize_doc(staff_doc),
        "tempPassword": temp_password,
        "message": "Staff created successfully",
    }


@router.get("/")
async def list_staff(
    search: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(20),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    from app.modules.dealers.service import get_dealer_by_user_id
    staff_self = await db["staff_accounts"].find_one({"userId": str(current_user["_id"])})

    if current_user["role"] == "DEALER_ADMIN":
        dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
        dealer_id = dealer["_id"]
    elif staff_self:
        dealer_id = staff_self["dealerId"]
    else:
        return {"total": 0, "staff": []}

    query = {"dealerId": dealer_id}
    if search:
        query["$or"] = [
            {"fullName": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"position": {"$regex": search, "$options": "i"}},
        ]

    total = await db["staff_accounts"].count_documents(query)
    staff_docs = await db["staff_accounts"].find(query).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "staff": [serialize_doc(s) for s in staff_docs]}


@router.get("/{staff_id}")
async def get_staff(staff_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    if ObjectId.is_valid(staff_id):
        staff = await db["staff_accounts"].find_one({"_id": ObjectId(staff_id)})
    else:
        staff = await db["staff_accounts"].find_one({"staffId": staff_id})
    if not staff:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Staff not found")
    return serialize_doc(staff)


@router.patch("/{staff_id}")
async def update_staff(
    staff_id: str,
    data: StaffUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    if ObjectId.is_valid(staff_id):
        query = {"_id": ObjectId(staff_id)}
    else:
        query = {"staffId": staff_id}

    update = data.model_dump(exclude_none=True)
    update["updatedAt"] = datetime.utcnow()
    await db["staff_accounts"].update_one(query, {"$set": update})
    updated = await db["staff_accounts"].find_one(query)
    return serialize_doc(updated)


@router.patch("/{staff_id}/permissions")
async def update_permissions(
    staff_id: str,
    data: StaffPermissionsRequest,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    if ObjectId.is_valid(staff_id):
        query = {"_id": ObjectId(staff_id)}
    else:
        query = {"staffId": staff_id}

    await db["staff_accounts"].update_one(
        query,
        {"$set": {"permissions": data.permissions, "updatedAt": datetime.utcnow()}},
    )
    return {"message": "Permissions updated"}


@router.post("/{staff_id}/toggle-suspend")
async def toggle_suspend(staff_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    if ObjectId.is_valid(staff_id):
        staff = await db["staff_accounts"].find_one({"_id": ObjectId(staff_id)})
    else:
        staff = await db["staff_accounts"].find_one({"staffId": staff_id})

    if not staff:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")

    new_status = "suspended" if staff["status"] == "active" else "active"
    await db["staff_accounts"].update_one(
        {"_id": staff["_id"]}, {"$set": {"status": new_status}}
    )
    if staff.get("userId"):
        await db["users"].update_one(
            {"_id": ObjectId(staff["userId"])},
            {"$set": {"status": new_status}},
        )
    return {"message": f"Staff {new_status}"}


@router.delete("/{staff_id}")
async def delete_staff(staff_id: str, current_user: dict = Depends(get_current_user)):
    db = get_db()
    if ObjectId.is_valid(staff_id):
        staff = await db["staff_accounts"].find_one({"_id": ObjectId(staff_id)})
    else:
        staff = await db["staff_accounts"].find_one({"staffId": staff_id})

    if not staff:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")

    await db["staff_accounts"].delete_one({"_id": staff["_id"]})
    if staff.get("userId"):
        await db["users"].update_one(
            {"_id": ObjectId(staff["userId"])},
            {"$set": {"status": "deleted", "role": "DELETED"}},
        )
    return {"message": "Staff removed"}
