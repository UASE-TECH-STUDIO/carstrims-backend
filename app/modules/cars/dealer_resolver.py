"""
Dealer ID resolver for cars endpoints.
Works for DEALER_ADMIN, DEALER_STAFF, and SYSTEM_ADMIN roles.
"""
from bson import ObjectId
from app.database.connection import get_db


async def resolve_dealer_id(user: dict) -> tuple[str | None, bool]:
    """
    Returns (dealer_mongo_id, is_admin).
    dealer_mongo_id: the MongoDB _id string of the dealer to filter by.
    is_admin: True if the user is SYSTEM_ADMIN (no filter needed).
    """
    db = get_db()
    uid = str(user["_id"])
    role = user.get("role", "")

    if role == "SYSTEM_ADMIN":
        return None, True  # Admin sees all

    if role == "DEALER_ADMIN":
        dealer = await db["dealer_organizations"].find_one({"userId": uid})
        if dealer:
            return str(dealer["_id"]), False
        return None, False

    if role == "DEALER_STAFF":
        # Look up staff_accounts to get dealerId
        staff = await db["staff_accounts"].find_one({"userId": uid})
        if staff:
            dealer_id_raw = staff.get("dealerId")
            if dealer_id_raw:
                did = str(dealer_id_raw)
                # Verify the dealer exists
                if ObjectId.is_valid(did):
                    dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(did)})
                else:
                    dealer = await db["dealer_organizations"].find_one({"dealerId": did})
                if dealer:
                    return str(dealer["_id"]), False
        return None, False

    return None, False
