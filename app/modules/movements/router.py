from fastapi import APIRouter, Depends, Query, Body
from typing import Optional
from pydantic import BaseModel
from app.auth.dependencies import get_current_dealer, get_current_dealer_or_staff, get_current_user
from app.modules.dealers.service import get_dealer_by_user_id, serialize_doc
from app.database.connection import get_db
from bson import ObjectId
from datetime import datetime
import random, string


class MovementCreateRequest(BaseModel):
    carId: str
    takenByName: str
    takenByPhone: Optional[str] = None
    takenByAddress: Optional[str] = None
    takenByIdType: Optional[str] = None
    takenByIdNumber: Optional[str] = None
    takenByIdImageUrl: Optional[str] = None
    purpose: Optional[str] = "test_drive"
    expectedReturnTime: Optional[str] = None
    permittedBy: Optional[str] = None
    approvalType: Optional[str] = "self"
    approverUserIds: Optional[List[str]] = []
    notes: Optional[str] = None


class MovementReturnRequest(BaseModel):
    returnedToName: Optional[str] = None
    condition: Optional[str] = "good"
    notes: Optional[str] = None


router = APIRouter(prefix="/api/v1/movements", tags=["Movements"])


def gen_id():
    return "MOV-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


@router.post("/")
async def log_movement(
    data: MovementCreateRequest,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)

    car = await db["car_listings"].find_one({
        "carId": data.carId, "dealerId": dealer["_id"]
    })
    if not car:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Car not found in your inventory")

    doc = {
        "movementId": gen_id(),
        "carId": data.carId,
        "carMongoId": str(car["_id"]),
        "carBrand": car.get("brand"),
        "carModel": car.get("model"),
        "carYear": car.get("year"),
        "dealerId": dealer["_id"],
        "loggedBy": str(current_user["_id"]),
        "takenByName": data.takenByName,
        "takenByPhone": data.takenByPhone,
        "takenByAddress": data.takenByAddress,
        "takenByIdType": data.takenByIdType,
        "takenByIdNumber": data.takenByIdNumber,
        "takenByIdImageUrl": data.takenByIdImageUrl,
        "purpose": data.purpose,
        "expectedReturnTime": data.expectedReturnTime,
        "permittedBy": data.permittedBy,
        "notes": data.notes,
        "status": "out",
        "approvalType": data.approvalType or "self",
        "approverUserIds": data.approverUserIds or [],
        "approvalStatus": "approved" if (data.approvalType == "self") else "pending",
        "approvedBy": str(current_user["_id"]) if (data.approvalType == "self") else None,
        "approvedByName": current_user.get("fullName") if (data.approvalType == "self") else None,
        "approvedAt": datetime.utcnow() if (data.approvalType == "self") else None,
        "timeOut": datetime.utcnow(),
        "timeReturned": None,
        "returnedToName": None,
        "returnCondition": None,
        "editHistory": [],
        "createdAt": datetime.utcnow(),
    }

    await db["car_listings"].update_one(
        {"_id": car["_id"]},
        {"$set": {"status": "out_for_inspection", "updatedAt": datetime.utcnow()}},
    )

    result = await db["vehicle_movement_logs"].insert_one(doc)
    doc["_id"] = result.inserted_id
    movement_id = str(result.inserted_id)

    # Notify approvers for non-self approval (non-blocking)
    approval_type = data.approvalType or "self"
    if approval_type != "self":
        try:
            import asyncio as _ai
            from app.modules.notifications.push_service import send_web_push_to_user as _wp
            car_name = f"{car.get('brand','')} {car.get('model','')}".strip() or data.carId
            notif_msg = f"{current_user.get('fullName','Someone')} requests movement approval for {car_name}"

            notify_ids = set()

            # Always notify dealer admin
            if dealer.get("userId"):
                notify_ids.add(str(dealer["userId"]))

            # Add selected approvers
            for uid in (data.approverUserIds or []):
                if uid:
                    notify_ids.add(uid)

            # If "everyone" - add all active staff
            if approval_type == "everyone":
                all_staff = await db["staff_accounts"].find(
                    {"dealerId": dealer["_id"], "status": {"$ne": "suspended"}}
                ).to_list(50)
                for s in all_staff:
                    if s.get("userId"):
                        notify_ids.add(str(s["userId"]))

            # Remove self
            notify_ids.discard(str(current_user["_id"]))

            for uid in notify_ids:
                await db["notifications"].insert_one({
                    "receiverId": uid,
                    "type": "movement_approval",
                    "title": "Movement Approval Required",
                    "message": notif_msg,
                    "data": {"movementId": movement_id},
                    "isRead": False,
                    "createdAt": datetime.utcnow(),
                })
                _ai.create_task(_wp(uid, "Movement Approval Required", notif_msg, "/dashboard"))
        except Exception as _e:
            print(f"[Movement] Notification error: {_e}")
    return serialize_doc(doc)


@router.get("/")
async def list_movements(
    status: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(30),
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)

    query = {"dealerId": dealer["_id"]}
    if status:
        query["status"] = status

    total = await db["vehicle_movement_logs"].count_documents(query)
    movs = await db["vehicle_movement_logs"].find(query).sort(
        "createdAt", -1
    ).skip(skip).limit(limit).to_list(limit)

    return {"total": total, "movements": [serialize_doc(m) for m in movs]}


@router.patch("/{movement_id}/return")
async def return_vehicle(
    movement_id: str,
    data: MovementReturnRequest,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)

    mov = await db["vehicle_movement_logs"].find_one({
        "movementId": movement_id, "dealerId": dealer["_id"]
    })
    if not mov:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Movement not found")

    now = datetime.utcnow()
    await db["vehicle_movement_logs"].update_one(
        {"movementId": movement_id},
        {"$set": {
            "status": "returned",
            "timeReturned": now,
            "returnedToName": data.returnedToName or str(current_user["_id"]),
            "returnCondition": data.condition,
            "returnNotes": data.notes,
            "updatedAt": now,
        }},
    )

    await db["car_listings"].update_one(
        {"carId": mov["carId"]},
        {"$set": {"status": "available", "updatedAt": now}},
    )

    updated = await db["vehicle_movement_logs"].find_one({"movementId": movement_id})
    return serialize_doc(updated)


@router.patch("/{movement_id}/edit")
async def edit_movement(
    movement_id: str,
    data: dict = Body(...),
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    db = get_db()
    dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)

    mov = await db["vehicle_movement_logs"].find_one({
        "movementId": movement_id, "dealerId": dealer["_id"]
    })
    if not mov:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Movement not found")

    edit_history = mov.get("editHistory", [])
    edit_history.append({
        "editedAt": datetime.utcnow().isoformat(),
        "editedBy": str(current_user["_id"]),
        "previous": {
            "takenByName": mov.get("takenByName"),
            "takenByPhone": mov.get("takenByPhone"),
            "purpose": mov.get("purpose"),
            "notes": mov.get("notes"),
        },
        "reason": data.get("editReason", ""),
    })

    allowed = [
        "takenByName","takenByPhone","takenByAddress",
        "takenByIdType","takenByIdNumber","takenByIdImageUrl",
        "purpose","expectedReturnTime","permittedBy","notes",
    ]
    update = {k: v for k, v in data.items() if k in allowed}
    update["editHistory"] = edit_history
    update["updatedAt"] = datetime.utcnow()

    await db["vehicle_movement_logs"].update_one(
        {"movementId": movement_id}, {"$set": update}
    )
    updated = await db["vehicle_movement_logs"].find_one({"movementId": movement_id})
    return serialize_doc(updated)


#  MULTI-DEALER MOVEMENT APPROVAL 

@router.post("/pending-approval")
async def request_movement_approval(
    data: dict = Body({}),
    current_user: dict = Depends(get_current_user),
):
    """
    Staff requests approval for a car movement.
    Notifies ALL dealers on the platform (or specific dealer if dealerId given).
    Any dealer who approves will lock the movement to them.
    """
    db = get_db()
    uid = str(current_user["_id"])

    # Build movement approval request
    req_id = "MVREQ-" + "".join(__import__("random").choices(__import__("string").ascii_uppercase + __import__("string").digits, k=8))
    doc = {
        "requestId": req_id,
        "requestedBy": uid,
        "requestedByName": current_user.get("fullName"),
        "carId": data.get("carId"),
        "purpose": data.get("purpose"),
        "expectedReturnTime": data.get("expectedReturnTime"),
        "notes": data.get("notes"),
        "takenByName": data.get("takenByName"),
        "takenByPhone": data.get("takenByPhone"),
        "status": "pending_approval",
        "approvedBy": None,
        "approvedAt": None,
        "targetDealerId": data.get("dealerId"),  # None = notify all
        "createdAt": datetime.utcnow(),
    }
    await db["movement_approval_requests"].insert_one(doc)

    # Notify dealers
    if data.get("dealerId") and ObjectId.is_valid(str(data["dealerId"])):
        # Specific dealer
        dealer = await db["dealer_organizations"].find_one({"_id": ObjectId(data["dealerId"])})
        if dealer and dealer.get("userId"):
            await db["notifications"].insert_one({
                "receiverId": str(dealer["userId"]),
                "senderId": uid,
                "type": "movement_approval",
                "title": "Vehicle Movement Approval Requested",
                "message": f"{current_user.get('fullName')} is requesting approval to move {data.get('carId')} for {data.get('purpose')}.",
                "isRead": False,
                "createdAt": datetime.utcnow(),
                "data": {"requestId": req_id},
            })
            try:
                import asyncio as _ai
                from app.modules.notifications.push_service import send_web_push_to_user as _wp
                _ai.create_task(_wp(str(dealer_doc["userId"]), "Vehicle Movement Approval Requested", f"{current_user.get('fullName')} requests approval to move a vehicle.", "/dashboard"))
            except Exception:
                pass
    else:
        # Notify all active dealers
        dealers = await db["dealer_organizations"].find({"status": "approved"}, {"userId": 1}).to_list(1000)
        notifs = [{
            "receiverId": str(d["userId"]),
            "senderId": uid,
            "type": "movement_approval",
            "title": "Vehicle Movement Approval Requested",
            "message": f"{current_user.get('fullName')} requests approval to move vehicle {data.get('carId')} for {data.get('purpose')}. Approve if available.",
            "isRead": False,
            "createdAt": datetime.utcnow(),
            "data": {"requestId": req_id},
        } for d in dealers if d.get("userId")]
        if notifs:
            await db["notifications"].insert_many(notifs)
            # Push to all notified dealers
            try:
                import asyncio as _aib
                from app.modules.notifications.push_service import send_web_push_to_user as _wpb
                for _d in dealers:
                    if _d.get("userId"):
                        _aib.create_task(_wpb(str(_d["userId"]), "Vehicle Movement Approval Requested", f"{current_user.get('fullName')} requests approval to move a vehicle.", "/dashboard"))
            except Exception:
                pass

    return {"message": "Approval request sent", "requestId": req_id}


@router.post("/pending-approval/{req_id}/approve")
async def approve_movement_request(
    req_id: str,
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    """Any dealer can approve a pending movement request."""
    db = get_db()
    from app.modules.dealers.service import get_dealer_by_user_id
    try:
        dealer = await get_dealer_by_user_id(str(current_user["_id"]), current_user)
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(403, "Not a dealer account")

    req = await db["movement_approval_requests"].find_one(
        {"requestId": req_id, "status": "pending_approval"}
    )
    if not req:
        from fastapi import HTTPException
        raise HTTPException(404, "Request not found or already approved")

    await db["movement_approval_requests"].update_one(
        {"requestId": req_id},
        {"$set": {
            "status": "approved",
            "approvedBy": str(current_user["_id"]),
            "approvedByName": current_user.get("fullName"),
            "approvedByDealerId": str(dealer["_id"]),
            "approvedByDealerName": dealer.get("companyName"),
            "approvedAt": datetime.utcnow(),
        }}
    )

    # Notify requester
    await db["notifications"].insert_one({
        "receiverId": str(req["requestedBy"]),
        "senderId": str(current_user["_id"]),
        "type": "movement_approved",
        "title": "Movement Approved",
        "message": f"{dealer.get('companyName')} has approved your vehicle movement request for {req.get('carId')}.",
        "isRead": False,
        "createdAt": datetime.utcnow(),
        "data": {"requestId": req_id},
    })
    try:
        import asyncio as _ai2
        from app.modules.notifications.push_service import send_web_push_to_user as _wp2
        _ai2.create_task(_wp2(str(req["requestedBy"]), "Movement Approved", f"{dealer.get('companyName')} approved your movement request.", "/dashboard"))
    except Exception:
        pass

    return {
        "message": "Movement approved",
        "approvedBy": current_user.get("fullName"),
        "dealerName": dealer.get("companyName"),
    }


@router.get("/pending-approvals")
async def get_pending_movement_approvals(
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    """Get all pending movement approval requests - available to all dealers."""
    db = get_db()
    reqs = await db["movement_approval_requests"].find(
        {"status": "pending_approval"}
    ).sort("createdAt", -1).to_list(100)
    from app.modules.dealers.service import serialize_doc
    return [serialize_doc(r) for r in reqs]

@router.get("/approvers")
async def get_available_approvers(
    current_user: dict = Depends(get_current_dealer_or_staff),
):
    """
    Returns list of all dealers and staff for this company
    who can approve a movement. Used to build the 'send to' picker.
    """
    from app.modules.dealers.service import get_dealer_by_user_id
    db = get_db()
    uid = str(current_user["_id"])
    role = current_user.get("role")

    # Resolve dealerId
    dealer_id = None
    if role == "DEALER_ADMIN":
        try:
            d = await get_dealer_by_user_id(uid)
            dealer_id = str(d["_id"])
        except Exception:
            pass
    elif role == "DEALER_STAFF":
        staff = await db["staff_accounts"].find_one({"userId": uid})
        if staff:
            dealer_id = str(staff.get("dealerId",""))

    if not dealer_id:
        return {"approvers": []}

    approvers = []

    # Add the dealer admin
    dealer_doc = await db["dealer_organizations"].find_one(
        {"_id": ObjectId(dealer_id)} if ObjectId.is_valid(dealer_id) else {"dealerId": dealer_id}
    )
    if dealer_doc:
        owner = await db["users"].find_one({"_id": ObjectId(dealer_doc["userId"])}) if dealer_doc.get("userId") else None
        approvers.append({
            "id":    str(dealer_doc["_id"]),
            "userId": str(dealer_doc.get("userId","")),
            "name":  owner.get("fullName","Dealer") if owner else dealer_doc.get("companyName","Dealer"),
            "role":  "DEALER_ADMIN",
            "position": "Dealer / Owner",
        })

    # Add all active staff
    staff_list = await db["staff_accounts"].find(
        {"dealerId": dealer_id, "status": {"$nin": ["suspended","deleted"]}}
    ).to_list(50)
    for s in staff_list:
        approvers.append({
            "id":       str(s["_id"]),
            "userId":   str(s.get("userId","")),
            "name":     s.get("fullName","Staff"),
            "role":     "DEALER_STAFF",
            "position": s.get("position","Staff"),
            "permissions": s.get("permissions",[]),
        })

    return {"approvers": approvers}
