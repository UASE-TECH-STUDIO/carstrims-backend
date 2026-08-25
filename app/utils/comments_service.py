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
    if car.get("adminMuted"):
        raise HTTPException(status_code=403, detail="Comments have been disabled on this listing.")

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
    await db["car_listings"].update_one({"carId": car_id}, {"$inc": {"commentCount": 1}})
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


async def delete_comment(comment_id: str, user_id: str, is_admin: bool = False) -> dict:
    db = get_db()
    comment = await db["car_comments"].find_one({"commentId": comment_id})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    # BUG FIX: the car detail page already shows a delete button to
    # SYSTEM_ADMIN for every comment, but this check rejected anyone
    # who wasn't the comment's own author — so admins clicking delete
    # got a silent 403 (swallowed by an empty catch block on the
    # frontend) and nothing appeared to happen.
    if not is_admin and comment["userId"] != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own comments")
    await db["car_comments"].delete_one({"commentId": comment_id})
    await db["car_listings"].update_one({"carId": comment["carId"]}, {"$inc": {"commentCount": -1}})
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
        "userPic": user.get("profilePicture") if user else None,
        "text": text,
        "likes": 0,
        "createdAt": datetime.utcnow().isoformat(),
    }

    await db["car_comments"].update_one(
        {"commentId": comment_id},
        {"$push": {"replies": reply}},
    )
    return {"message": "Reply added", "reply": reply}


async def toggle_comment_like(user_id: str, comment_id: str) -> dict:
    """Same pattern as toggle_like() for cars: a separate collection
    tracks (userId, commentId) pairs so a user can't like the same
    comment twice, with the comment's own likes counter kept in sync
    via $inc rather than recounting the tracking collection on every
    read."""
    db = get_db()
    comment = await db["car_comments"].find_one({"commentId": comment_id})
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    existing = await db["comment_likes"].find_one({"userId": user_id, "commentId": comment_id})
    if existing:
        await db["comment_likes"].delete_one({"userId": user_id, "commentId": comment_id})
        await db["car_comments"].update_one({"commentId": comment_id}, {"$inc": {"likes": -1}})
        return {"liked": False}
    else:
        await db["comment_likes"].insert_one({
            "userId": user_id, "commentId": comment_id, "createdAt": datetime.utcnow(),
        })
        await db["car_comments"].update_one({"commentId": comment_id}, {"$inc": {"likes": 1}})
        return {"liked": True}


async def toggle_reply_like(user_id: str, comment_id: str, reply_id: str) -> dict:
    """Same pattern as toggle_comment_like, one level deeper: replies
    live as subdocuments inside a comment's replies array rather than
    their own collection, so updating a specific reply's like count
    uses Mongo's positional $ operator against a query that matches
    both the parent comment and the specific reply by replyId, rather
    than a plain top-level update."""
    db = get_db()
    comment = await db["car_comments"].find_one({"commentId": comment_id, "replies.replyId": reply_id})
    if not comment:
        raise HTTPException(status_code=404, detail="Reply not found")

    existing = await db["reply_likes"].find_one({"userId": user_id, "replyId": reply_id})
    if existing:
        await db["reply_likes"].delete_one({"userId": user_id, "replyId": reply_id})
        await db["car_comments"].update_one(
            {"commentId": comment_id, "replies.replyId": reply_id},
            {"$inc": {"replies.$.likes": -1}},
        )
        return {"liked": False}
    else:
        await db["reply_likes"].insert_one({
            "userId": user_id, "replyId": reply_id, "commentId": comment_id, "createdAt": datetime.utcnow(),
        })
        await db["car_comments"].update_one(
            {"commentId": comment_id, "replies.replyId": reply_id},
            {"$inc": {"replies.$.likes": 1}},
        )
        return {"liked": True}


async def get_reply_like_status(user_id: str, reply_ids: list) -> list:
    """Bulk lookup, same reasoning as get_comment_like_status - one
    request for every reply on a page rather than one per reply."""
    db = get_db()
    liked = await db["reply_likes"].find(
        {"userId": user_id, "replyId": {"$in": reply_ids}}
    ).to_list(len(reply_ids))
    return [l["replyId"] for l in liked]


async def get_comment_like_status(user_id: str, comment_ids: list) -> list:
    """Bulk lookup so the frontend can mark which of a whole page of
    comments the current user has already liked in one request,
    rather than one request per comment."""
    db = get_db()
    liked = await db["comment_likes"].find(
        {"userId": user_id, "commentId": {"$in": comment_ids}}
    ).to_list(len(comment_ids))
    return [l["commentId"] for l in liked]


async def backfill_comment_counts() -> int:
    """One-time-per-startup backfill for the commentCount field added
    after cars/comments already existed - without this, any car with
    comments posted before that field existed would show 0 forever,
    since the $inc-on-post/delete approach only keeps a count in sync
    going forward, not retroactively.

    Idempotent by construction (always recomputes the real count from
    car_comments rather than blindly incrementing), so it's safe to
    run on every startup rather than needing a one-shot migration
    flag - a car with the correct count already set just gets set to
    the same value again.

    Uses an aggregation pipeline + a single bulk_write rather than a
    per-document loop, so this stays cheap even as the collection
    grows - one grouped count query plus one bulk update, not N
    round trips."""
    from pymongo import UpdateOne

    db = get_db()
    counts = await db["car_comments"].aggregate([
        {"$group": {"_id": "$carId", "count": {"$sum": 1}}}
    ]).to_list(None)

    if not counts:
        return 0

    ops = [
        UpdateOne({"carId": c["_id"]}, {"$set": {"commentCount": c["count"]}})
        for c in counts
    ]
    result = await db["car_listings"].bulk_write(ops, ordered=False)
    return result.modified_count
