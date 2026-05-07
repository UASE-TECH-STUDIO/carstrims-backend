from datetime import datetime
from bson import ObjectId
from fastapi import HTTPException
from app.database.connection import get_db
from app.modules.dealers.service import serialize_doc
import random
import string


async def add_comment(user_id: str, car_id: str, text: str) -> dict:
    db = get_db()

    car = await db["car_listings"].find_one({"carId": car_id})
    if not car:
        raise HTTPException(status_code=404, detail="Car not found")

    user = await db["users"].find_one({"_id": ObjectId(user_id)})

    comment_doc = {
        "commentId": "CMT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8)),
        "carId": car_id,
        "userId": user_id,
        "userName": user.get("fullName", "Anonymous") if user else "Anonymous",
        "userPic": user.get("profilePicture") if user else None,
        "text": text,
        "likes": 0,
        "replies": [],
        "createdAt": datetime.utcnow(),
    }

    result = await db["car_comments"].insert_one(comment_doc)
    comment_doc["_id"] = result.inserted_id
    return serialize_doc(comment_doc)


async def get_car_comments(car_id: str, skip: int = 0, limit: int = 20) -> dict:
    db = get_db()
    total = await db["car_comments"].count_documents({"carId": car_id})
    comments = await db["car_comments"].find(
        {"carId": car_id}
    ).sort("createdAt", -1).skip(skip).limit(limit).to_list(limit)
    return {
        "total": total,
        "comments": [serialize_doc(c) for c in comments],
    }


async def delete_comment(comment_id: str, user_id: str) -> dict:
    db = get_db()
    comment = await db["car_comments"].find_one({"commentId": comment_id})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment["userId"] != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own comments")
    await db["car_comments"].delete_one({"commentId": comment_id})
    return {"message": "Comment deleted"}


async def add_reply(user_id: str, comment_id: str, text: str) -> dict:
    db = get_db()
    comment = await db["car_comments"].find_one({"commentId": comment_id})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    user = await db["users"].find_one({"_id": ObjectId(user_id)})
    reply = {
        "replyId": "RPL-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6)),
        "userId": user_id,
        "userName": user.get("fullName", "Anonymous") if user else "Anonymous",
        "text": text,
        "createdAt": datetime.utcnow().isoformat(),
    }

    await db["car_comments"].update_one(
        {"commentId": comment_id},
        {"$push": {"replies": reply}},
    )
    return {"message": "Reply added", "reply": reply}
