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
    message: str


def gen_msg_id():
    return "MSG-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

def gen_conv_id():
    return "CONV-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


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

    if not existing:
        conv_doc = {
            "conversationId": gen_conv_id(),
            "participants": [uid, receiver_mongo_id],
            "lastMessage": data.message,
            "lastMessageAt": now,
            "createdAt": now,
        }
        await db["conversations"].insert_one(conv_doc)
        conv_id = conv_doc["conversationId"]
    else:
        conv_id = existing["conversationId"]
        await db["conversations"].update_one(
            {"conversationId": conv_id},
            {"$set": {"lastMessage": data.message, "lastMessageAt": now}},
        )

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

    # Resolve receiver to MongoDB _id if needed
    receiver_id = data.receiverId
    if not ObjectId.is_valid(receiver_id):
        recv_user = await db["users"].find_one({"userId": receiver_id})
        if recv_user:
            receiver_id = str(recv_user["_id"])

    msg_doc = {
        "messageId": gen_msg_id(),
        "conversationId": conv_id,
        "senderId": uid,
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
            "lastMessage": data.imageUrl and "📷 Photo" or data.message,
            "lastMessageAt": now,
        }},
    )

    await db["notifications"].insert_one({
        "receiverId": receiver_id,
        "senderId": uid,
        "type": "message",
        "title": f"New message from {current_user.get('fullName', 'Someone')}",
        "message": data.imageUrl and "📷 Sent a photo" or data.message[:80],
        "isRead": False,
        "data": {"conversationId": conv_id},
        "createdAt": now,
    })

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
