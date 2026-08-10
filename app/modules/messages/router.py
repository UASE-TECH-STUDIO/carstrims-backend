from fastapi import APIRouter, Depends, Query, UploadFile, File
from typing import Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_user
from app.modules.dealers.service import serialize_doc
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime
import random, string, cloudinary, cloudinary.uploader
from app.config.settings import settings

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET,
)


class MessageSend(BaseModel):
    receiverId: str
    message: str
    imageUrl: Optional[str] = None


class ConversationStart(BaseModel):
    receiverId: str
    message: Optional[str] = None      # optional  user drafts it themselves
    carId: Optional[str] = None        # car being enquired about
    carBrand: Optional[str] = None
    carModel: Optional[str] = None
    carYear: Optional[int] = None
    carImage: Optional[str] = None
    carPrice: Optional[float] = None


def gen_msg_id():
    return "MSG-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

def gen_conv_id():
    return "CONV-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


async def resolve_effective_sender(db, current_user: dict, conv_id: str) -> dict:
    """
    Figures out who a message should be attributed to.

    For DEALER_ADMIN (and everyone else): the message is simply from them.

    For DEALER_STAFF: if the conversation they're replying in actually
    belongs to their dealer (i.e. they're helping manage the dealer's own
    conversation, the "sync" feature), the message is stored as coming
    from the DEALER (so the conversation's participants list — and
    anyone external like a customer — stays consistent, and the dealer
    always sees their own team's replies as "their side" of the chat).
    The staff member's own id/name is additionally recorded so the
    dealer (or other staff) can see who on the team actually typed it,
    without that identity leaking to the external participant.

    If the staff member is instead in a normal, direct conversation of
    their own (not the synced dealer inbox), they're just themselves —
    no substitution happens.
    """
    uid = str(current_user["_id"])
    result = {"senderId": uid, "sentByStaffId": None, "sentByStaffName": None}

    if current_user.get("role") != "DEALER_STAFF":
        return result

    staff = await db["staff_accounts"].find_one({"userId": uid})
    if not staff:
        return result

    did = staff.get("dealerId")
    dealer = None
    if isinstance(did, ObjectId):
        dealer = await db["dealer_organizations"].find_one({"_id": did})
    elif did and ObjectId.is_valid(str(did)):
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(str(did))})
    if not dealer or not dealer.get("userId"):
        return result

    dealer_user = None
    if ObjectId.is_valid(str(dealer["userId"])):
        dealer_user = await db["users"].find_one({"_id": ObjectId(str(dealer["userId"]))})
    if not dealer_user:
        dealer_user = await db["users"].find_one({"userId": str(dealer["userId"])})
    if not dealer_user:
        return result

    dealer_uid = str(dealer_user["_id"])

    # Only substitute if this conversation genuinely belongs to the dealer
    # (staff shouldn't be able to impersonate the dealer in conversations
    # that have nothing to do with them).
    conv = await db["conversations"].find_one({"conversationId": conv_id})
    if not conv or dealer_uid not in conv.get("participants", []):
        return result

    return {
        "senderId": dealer_uid,
        "sentByStaffId": uid,
        "sentByStaffName": current_user.get("fullName"),
    }


router = APIRouter(prefix="/api/v1/messages", tags=["Messages"])


@router.get("/conversations")
async def list_conversations(current_user: dict = Depends(get_current_user)):
    db = get_db()
    uid = str(current_user["_id"])

    convs = await db["conversations"].find(
        {"participants": uid}
    ).sort("lastMessageAt", -1).to_list(100)

    result = []
    for conv in convs:
        s = serialize_doc(conv)
        other_id = next((p for p in conv.get("participants", []) if p != uid), None)
        if other_id and ObjectId.is_valid(other_id):
            other = await db["users"].find_one({"_id": ObjectId(other_id)})
            if other:
                s["otherUser"] = {
                    "userId": str(other["_id"]),
                    "fullName": other.get("fullName"),
                    "role": other.get("role"),
                    "profilePicture": other.get("profilePicture"),
                    "email": other.get("email"),
                }
        s["unreadCount"] = await db["messages"].count_documents({
            "conversationId": conv["conversationId"],
            "receiverId": uid,
            "isRead": False,
        })
        result.append(s)
    return result



@router.get("/dealer-conversations")
async def get_dealer_conversations(
    current_user: dict = Depends(get_current_user),
):
    """
    Returns the DEALER's conversations for staff to view and manage.
    Staff can help the dealer by viewing and responding to their messages.
    Messages sent from here appear to come from the dealer, not the staff.
    """
    db = get_db()
    role = current_user.get("role")
    if role != "DEALER_STAFF":
        # For dealer admin, just return their own conversations
        return await list_conversations.__wrapped__(current_user) if hasattr(list_conversations, '__wrapped__') else []

    # Get staff account to find dealer
    uid = str(current_user["_id"])
    staff = await db["staff_accounts"].find_one({"userId": uid})
    if not staff:
        return []

    # Find dealer
    from bson import ObjectId as _OID
    did = staff.get("dealerId")
    dealer = None
    if isinstance(did, _OID):
        dealer = await db["dealer_organizations"].find_one({"_id": did})
    elif did and _OID.is_valid(str(did)):
        dealer = await db["dealer_organizations"].find_one({"_id": _OID(str(did))})
    if not dealer:
        return []

    # Get dealer user account
    dealer_user = None
    if dealer.get("userId"):
        if _OID.is_valid(str(dealer["userId"])):
            dealer_user = await db["users"].find_one({"_id": _OID(str(dealer["userId"]))})
        if not dealer_user:
            dealer_user = await db["users"].find_one({"userId": str(dealer["userId"])})
    if not dealer_user:
        return []

    dealer_uid = str(dealer_user["_id"])

    # Fetch dealer's conversations
    convs = await db["conversations"].find(
        {"participants": dealer_uid}
    ).sort("lastMessageAt", -1).limit(50).to_list(50)

    result = []
    for conv in convs:
        # Get the other participant (not the dealer)
        other_uid = next((p for p in conv.get("participants", []) if p != dealer_uid), None)
        other_user = None
        if other_uid:
            if _OID.is_valid(other_uid):
                other_user = await db["users"].find_one({"_id": _OID(other_uid)})
            if not other_user:
                other_user = await db["users"].find_one({"userId": other_uid})

        # Get last message
        last_msg = await db["messages"].find_one(
            {"conversationId": conv.get("conversationId")},
            sort=[("createdAt", -1)]
        )

        unread = await db["messages"].count_documents({
            "conversationId": conv.get("conversationId"),
            "senderId": {"$ne": dealer_uid},
            "isRead": False,
        })

        c = serialize_doc(conv)
        c["otherUser"] = serialize_doc(other_user) if other_user else {}
        c["lastMessage"] = serialize_doc(last_msg) if last_msg else {}
        c["unreadCount"] = unread
        c["dealerUserId"] = dealer_uid  # so staff knows to send as dealer
        result.append(c)

    return result


@router.post("/start")
async def start_conversation(
    data: ConversationStart,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    uid = str(current_user["_id"])
    receiver_id = data.receiverId

    # Accept both MongoDB ObjectId strings and userId strings
    receiver = None
    if ObjectId.is_valid(receiver_id):
        receiver = await db["users"].find_one({"_id": ObjectId(receiver_id)})
    if not receiver:
        # Try by userId field (the string userId like "USR-XXXXXXXX")
        receiver = await db["users"].find_one({"userId": receiver_id})
    if not receiver:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")

    # Always use MongoDB _id string as the participant key
    receiver_mongo_id = str(receiver["_id"])

    # Check existing conversation
    existing = await db["conversations"].find_one({
        "participants": {"$all": [uid, receiver_mongo_id]}
    })

    now = datetime.utcnow()

    # Build car context if provided
    car_context = None
    if data.carId:
        car_context = {
            "carId": data.carId,
            "carBrand": data.carBrand,
            "carModel": data.carModel,
            "carYear": data.carYear,
            "carImage": data.carImage,
            "carPrice": data.carPrice,
        }
        # Fetch full car details if only carId given
        if not data.carBrand:
            car_doc = await db["car_listings"].find_one({"carId": data.carId})
            if car_doc:
                car_context["carBrand"] = car_doc.get("brand")
                car_context["carModel"] = car_doc.get("model")
                car_context["carYear"] = car_doc.get("year")
                car_context["carPrice"] = car_doc.get("sellingPrice")
                imgs = car_doc.get("images", [])
                car_context["carImage"] = imgs[0] if imgs else None

    if not existing:
        conv_doc = {
            "conversationId": gen_conv_id(),
            "participants": [uid, receiver_mongo_id],
            "lastMessage": data.message or "",
            "lastMessageAt": now,
            "carContext": car_context,
            "createdAt": now,
        }
        await db["conversations"].insert_one(conv_doc)
        conv_id = conv_doc["conversationId"]
    else:
        conv_id = existing["conversationId"]
        update_fields = {"lastMessageAt": now}
        if car_context:
            update_fields["carContext"] = car_context
        await db["conversations"].update_one(
            {"conversationId": conv_id},
            {"$set": update_fields},
        )

    # Only create message + notify if the user actually sent a message
    if data.message and data.message.strip():
        msg_doc = {
            "messageId": gen_msg_id(),
            "conversationId": conv_id,
            "senderId": uid,
            "receiverId": receiver_mongo_id,
            "message": data.message,
            "isRead": False,
            "createdAt": now,
        }
        await db["messages"].insert_one(msg_doc)

        await db["notifications"].insert_one({
            "receiverId": receiver_mongo_id,
            "senderId": uid,
            "type": "message",
            "title": f"New message from {current_user.get('fullName', 'Someone')}",
            "message": data.message[:80],
            "isRead": False,
            "data": {"conversationId": conv_id},
            "createdAt": now,
        })
        # Fire push notification
        try:
            import asyncio as _asyncio
            from app.modules.notifications.push_service import send_web_push_to_user as _swpu
            _asyncio.create_task(_swpu(
                receiver_mongo_id,
                f"New message from {current_user.get('fullName', 'Someone')}",
                data.message[:80],
                "/dashboard",
            ))
        except Exception as _pe:
            print(f"[Push] Message push error: {_pe}")

    return {"conversationId": conv_id, "message": "Conversation started"}


@router.get("/conversation/{conv_id}")
async def get_messages(
    conv_id: str,
    skip: int = Query(0),
    limit: int = Query(100),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    uid = str(current_user["_id"])

    msgs = await db["messages"].find(
        {"conversationId": conv_id}
    ).sort("createdAt", 1).skip(skip).limit(limit).to_list(limit)

    await db["messages"].update_many(
        {"conversationId": conv_id, "receiverId": uid, "isRead": False},
        {"$set": {"isRead": True}},
    )

    return [serialize_doc(m) for m in msgs]


@router.post("/conversation/{conv_id}/send")
async def send_message(
    conv_id: str,
    data: MessageSend,
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    uid = str(current_user["_id"])
    now = datetime.utcnow()

    sender = await resolve_effective_sender(db, current_user, conv_id)

    # Resolve receiver to MongoDB _id if needed
    receiver_id = data.receiverId
    if not ObjectId.is_valid(receiver_id):
        recv_user = await db["users"].find_one({"userId": receiver_id})
        if recv_user:
            receiver_id = str(recv_user["_id"])

    msg_doc = {
        "messageId": gen_msg_id(),
        "conversationId": conv_id,
        "senderId": sender["senderId"],
        "sentByStaffId": sender["sentByStaffId"],
        "sentByStaffName": sender["sentByStaffName"],
        "receiverId": receiver_id,
        "message": data.message,
        "imageUrl": data.imageUrl,  # photo in chat
        "isRead": False,
        "createdAt": now,
    }
    await db["messages"].insert_one(msg_doc)

    await db["conversations"].update_one(
        {"conversationId": conv_id},
        {"$set": {
            "lastMessage": data.imageUrl and " Photo" or data.message,
            "lastMessageAt": now,
        }},
    )

    await db["notifications"].insert_one({
        "receiverId": receiver_id,
        "senderId": uid,
        "type": "message",
        "title": f"New message from {current_user.get('fullName', 'Someone')}",
        "message": data.imageUrl and " Sent a photo" or data.message[:80],
        "isRead": False,
        "data": {"conversationId": conv_id},
        "createdAt": now,
    })
    # Fire push notification
    try:
        import asyncio as _asyncio2
        from app.modules.notifications.push_service import send_web_push_to_user as _swpu2
        _asyncio2.create_task(_swpu2(
            receiver_id,
            f"New message from {current_user.get('fullName', 'Someone')}",
            data.imageUrl and "Sent a photo" or data.message[:80],
            "/dashboard",
        ))
    except Exception as _pe2:
        print(f"[Push] Reply push error: {_pe2}")

    return serialize_doc(msg_doc)


@router.post("/conversation/{conv_id}/upload-image")
async def upload_chat_image(
    conv_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload a photo/screenshot during a chat conversation."""
    try:
        content = await file.read()
        result = cloudinary.uploader.upload(
            content,
            resource_type="image",
            folder="carstrims/chat-images",
        )
        return {"url": result["secure_url"], "name": file.filename}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Upload failed: {str(e)}")


@router.get("/search-users")
async def search_users(
    q: str = Query(..., min_length=1),
    current_user: dict = Depends(get_current_user),
):
    db = get_db()
    uid = str(current_user["_id"])

    users = await db["users"].find({
        "_id": {"$ne": ObjectId(uid)},
        "status": {"$ne": "deleted"},
        "$or": [
            {"fullName": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
            {"username": {"$regex": q, "$options": "i"}},
        ],
    }).limit(15).to_list(15)

    return [
        {
            "userId": str(u["_id"]),
            "fullName": u.get("fullName"),
            "email": u.get("email"),
            "role": u.get("role"),
            "profilePicture": u.get("profilePicture"),
        }
        for u in users
    ]


@router.post("/conversation/{conv_id}/upload-attachment")
async def upload_chat_attachment(
    conv_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """
    Upload any file type in a chat: image, video, or document.
    Returns url, name, size and type for the frontend to send as a message.
    """
    try:
        content = await file.read()
        content_type = file.content_type or ""

        if content_type.startswith("image/"):
            resource_type = "image"
            att_type = "image"
        elif content_type.startswith("video/"):
            resource_type = "video"
            att_type = "video"
        else:
            resource_type = "raw"
            att_type = "document"

        result = cloudinary.uploader.upload(
            content,
            resource_type=resource_type,
            folder="carstrims/chat-attachments",
            use_filename=True,
        )

        return {
            "url": result["secure_url"],
            "name": file.filename,
            "size": len(content),
            "type": att_type,     # "image" | "video" | "document"
            "isImage": att_type == "image",
            "isVideo": att_type == "video",
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Upload failed: {str(e)}")


@router.post("/conversation/{conv_id}/send-with-attachment")
async def send_message_with_attachment(
    conv_id: str,
    current_user: dict = Depends(get_current_user),
    message: str = "",
    receiverId: str = "",
    attachmentUrl: str = "",
    attachmentName: str = "",
    attachmentType: str = "image",
):
    """Send a message that includes an attachment URL (already uploaded)."""
    db = get_db()
    uid = str(current_user["_id"])
    now = datetime.utcnow()

    sender = await resolve_effective_sender(db, current_user, conv_id)

    receiver_id = receiverId
    if receiver_id and not ObjectId.is_valid(receiver_id):
        recv_user = await db["users"].find_one({"userId": receiver_id})
        if recv_user:
            receiver_id = str(recv_user["_id"])

    msg_doc = {
        "messageId": gen_msg_id(),
        "conversationId": conv_id,
        "senderId": sender["senderId"],
        "sentByStaffId": sender["sentByStaffId"],
        "sentByStaffName": sender["sentByStaffName"],
        "receiverId": receiver_id,
        "message": message or (" Photo" if attachmentType == "image" else " Video" if attachmentType == "video" else " Document"),
        "attachmentUrl": attachmentUrl,
        "attachmentName": attachmentName,
        "attachmentType": attachmentType,
        "isRead": False,
        "createdAt": now,
    }
    await db["messages"].insert_one(msg_doc)
    await db["conversations"].update_one(
        {"conversationId": conv_id},
        {"$set": {
            "lastMessage": msg_doc["message"],
            "lastMessageAt": now,
        }},
    )
    if receiver_id:
        await db["notifications"].insert_one({
            "receiverId": receiver_id,
            "senderId": uid,
            "type": "message",
            "title": f"New message from {current_user.get('fullName','Someone')}",
            "message": msg_doc["message"],
            "isRead": False,
            "data": {"conversationId": conv_id},
            "createdAt": now,
        })
    return serialize_doc(msg_doc)



@router.post("/command/reset-password/{target_user_id}")
async def admin_reset_password_command(
    target_user_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Admin command: reset a user's password and notify them.
    Called via !password command in chat or from admin dashboard.
    """
    if current_user.get("role") != "SYSTEM_ADMIN":
        from fastapi import HTTPException
        raise HTTPException(403, "Admin access required")
    admin = current_user
    from app.auth.password import hash_password
    import random, string
    db = get_db()

    q = {"_id": ObjectId(target_user_id)} if ObjectId.is_valid(target_user_id) else {"userId": target_user_id}
    user = await db["users"].find_one(q)
    if not user:
        from fastapi import HTTPException
        raise HTTPException(404, "User not found")

    new_password = "Carstrims@" + "".join(random.choices(string.digits, k=6))
    await db["users"].update_one(q, {"$set": {"passwordHash": hash_password(new_password), "updatedAt": datetime.utcnow()}})

    # Notify user via all channels
    try:
        from app.services.notifications import notify_password_reset
        import asyncio
        asyncio.create_task(notify_password_reset(user, new_password, method="email"))
    except Exception:
        pass

    await db["notifications"].insert_one({
        "receiverId": str(user["_id"]),
        "type": "general",
        "title": "Password Reset",
        "message": f"Your password has been reset by admin. New temporary password: {new_password}  Change it after login.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
    })

    return {
        "message": "Password reset successfully",
        "newPassword": new_password,
        "userId": str(user["_id"]),
        "userEmail": user.get("email"),
        "userName": user.get("fullName"),
    }

@router.get("/my-team")
async def get_my_team(current_user: dict = Depends(get_current_user)):
    """
    Returns the dealer's staff members (for quick messaging within the team).
    Works for both DEALER_ADMIN (gets their staff) and DEALER_STAFF (gets dealer + siblings).
    """
    db = get_db()
    uid = str(current_user["_id"])
    role = current_user.get("role")
    team = []

    if role == "DEALER_ADMIN":
        # Get all active staff for this dealer
        dealer = await db["dealer_organizations"].find_one({"userId": uid})
        if dealer:
            staff_list = await db["staff_accounts"].find(
                {"dealerId": dealer["_id"], "status": {"$ne": "suspended"}}
            ).to_list(50)
            for s in staff_list:
                if s.get("userId"):
                    u = await db["users"].find_one({"_id": ObjectId(s["userId"])})
                    if u:
                        team.append({
                            "userId":    str(u["_id"]),
                            "fullName":  s.get("fullName") or u.get("fullName"),
                            "email":     u.get("email"),
                            "role":      "DEALER_STAFF",
                            "position":  s.get("position","Staff"),
                            "profilePicture": u.get("profilePicture") or s.get("profilePicture"),
                            "isTeamMember": True,
                        })

    elif role == "DEALER_STAFF":
        # Get dealer + other staff in same company
        staff_self = await db["staff_accounts"].find_one({"userId": uid})
        if staff_self:
            dealer_id = staff_self.get("dealerId")
            # Add the dealer (owner)
            dealer = await db["dealer_organizations"].find_one({"_id": dealer_id})
            if dealer:
                owner = await db["users"].find_one({"_id": ObjectId(dealer["userId"])}) if dealer.get("userId") else None
                if owner:
                    team.append({
                        "userId":   str(owner["_id"]),
                        "fullName": dealer.get("companyName") or owner.get("fullName"),
                        "email":    owner.get("email"),
                        "role":     "DEALER_ADMIN",
                        "position": "Dealer / Owner",
                        "profilePicture": dealer.get("logo") or owner.get("profilePicture"),
                        "isTeamMember": True,
                    })
            # Add other staff
            siblings = await db["staff_accounts"].find(
                {"dealerId": dealer_id, "userId": {"$ne": uid}, "status": {"$ne": "suspended"}}
            ).to_list(50)
            for s in siblings:
                if s.get("userId"):
                    u = await db["users"].find_one({"_id": ObjectId(s["userId"])})
                    if u:
                        team.append({
                            "userId":   str(u["_id"]),
                            "fullName": s.get("fullName") or u.get("fullName"),
                            "email":    u.get("email"),
                            "role":     "DEALER_STAFF",
                            "position": s.get("position","Staff"),
                            "profilePicture": u.get("profilePicture"),
                            "isTeamMember": True,
                        })

    return team
