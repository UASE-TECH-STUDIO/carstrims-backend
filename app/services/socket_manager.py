"""
CARSTRIMS Socket.IO Manager
Handles real-time: notifications, chat, car feed updates
Replaces the separate Node.js socket-server
"""
import socketio
from jose import jwt
import logging
from app.config.settings import settings

log = logging.getLogger("carstrims.socket")

# ── Create async Socket.IO server ──────────────────────────────────────────
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    logger=False,
    engineio_logger=False,
)

# Track connected users: {socket_id: {userId, role, dealerId, email}}
connected_users: dict[str, dict] = {}


# ── Auth middleware ─────────────────────────────────────────────────────────
def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=["HS256"],
        )
        return payload
    except Exception:
        return None


# ── Connection ──────────────────────────────────────────────────────────────
@sio.event
async def connect(sid, environ, auth):
    token = None
    if auth and isinstance(auth, dict):
        token = auth.get("token")
    if not token:
        # Check headers
        headers = dict(environ.get("asgi.scope", {}).get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode()
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

    user_data = {}
    if token:
        payload = decode_token(token)
        if payload:
            user_data = {
                "userId": payload.get("sub"),
                "role":   payload.get("role"),
                "email":  payload.get("email"),
                "dealerId": payload.get("dealerId"),
            }

    connected_users[sid] = user_data

    # Join personal room
    if user_data.get("userId"):
        await sio.enter_room(sid, f"user:{user_data['userId']}")
        log.info(f"User {user_data['userId']} connected [{sid}]")

    # Join role room
    if user_data.get("role"):
        await sio.enter_room(sid, f"role:{user_data['role']}")

    # Join public feed
    await sio.enter_room(sid, "public:feed")

    await sio.emit("connected", {
        "socketId": sid,
        "userId": user_data.get("userId"),
        "status": "connected",
    }, to=sid)


@sio.event
async def disconnect(sid):
    user = connected_users.pop(sid, {})
    log.info(f"Disconnected: {sid} | user: {user.get('userId', 'guest')}")


# ── Chat events ─────────────────────────────────────────────────────────────
@sio.event
async def chat_join(sid, data):
    thread_id = data.get("threadId") if isinstance(data, dict) else data
    if thread_id:
        await sio.enter_room(sid, f"thread:{thread_id}")

@sio.event
async def chat_leave(sid, data):
    thread_id = data.get("threadId") if isinstance(data, dict) else data
    if thread_id:
        await sio.leave_room(sid, f"thread:{thread_id}")

@sio.event
async def chat_message(sid, data):
    user = connected_users.get(sid, {})
    sender_id = user.get("userId")
    if not sender_id or not isinstance(data, dict):
        return

    thread_id   = data.get("threadId")
    message     = data.get("message", "")
    receiver_id = data.get("receiverId")

    payload = {
        "threadId":   thread_id,
        "senderId":   sender_id,
        "senderRole": user.get("role"),
        "message":    message,
        "sentAt":     __import__("datetime").datetime.utcnow().isoformat(),
    }

    # Send to everyone in thread
    await sio.emit("chat:message:new", payload, room=f"thread:{thread_id}")

    # Notify receiver directly
    if receiver_id:
        await sio.emit("chat:notification", {
            "threadId": thread_id,
            "preview":  message[:60],
            "from":     sender_id,
        }, room=f"user:{receiver_id}")

@sio.event
async def chat_typing(sid, data):
    user = connected_users.get(sid, {})
    if not isinstance(data, dict):
        return
    thread_id = data.get("threadId")
    await sio.emit("chat:typing", {
        "userId":   user.get("userId"),
        "isTyping": data.get("isTyping", False),
    }, room=f"thread:{thread_id}", skip_sid=sid)


# ── Feed events ─────────────────────────────────────────────────────────────
@sio.event
async def feed_subscribe(sid, data=None):
    await sio.enter_room(sid, "public:feed")

@sio.event
async def feed_unsubscribe(sid, data=None):
    await sio.leave_room(sid, "public:feed")


# ── Notification events ─────────────────────────────────────────────────────
@sio.event
async def notification_read(sid, notification_id):
    await sio.emit("notification:read:ack", {
        "notificationId": notification_id
    }, to=sid)

@sio.event
async def notification_read_all(sid, data=None):
    await sio.emit("notification:read:all:ack", {"success": True}, to=sid)


# ── Helper functions (called from FastAPI routes) ───────────────────────────
async def notify_user(user_id: str, notification: dict):
    """Send notification to a specific user."""
    await sio.emit("notification:new", {
        **notification,
        "isRead": False,
        "createdAt": __import__("datetime").datetime.utcnow().isoformat(),
    }, room=f"user:{user_id}")
    log.info(f"Notified user {user_id}: {notification.get('title')}")


async def broadcast_new_car(car: dict):
    """Broadcast new car listing to public feed."""
    await sio.emit("feed:new:car", {
        "carId":        car.get("carId"),
        "brand":        car.get("brand"),
        "model":        car.get("model"),
        "year":         car.get("year"),
        "sellingPrice": car.get("sellingPrice"),
        "images":       car.get("images", []),
        "status":       car.get("status"),
        "city":         car.get("city"),
        "createdAt":    __import__("datetime").datetime.utcnow().isoformat(),
    }, room="public:feed")


async def broadcast_car_sold(car_id: str):
    """Broadcast car sold event to public feed."""
    await sio.emit("feed:car:sold", {"carId": car_id}, room="public:feed")


async def broadcast_to_room(room: str, event: str, data: dict):
    """Broadcast any event to any room."""
    await sio.emit(event, data, room=room)


async def notify_admins(event: str, data: dict):
    """Send event to all system admins."""
    await sio.emit(event, data, room="role:SYSTEM_ADMIN")


def get_connection_count() -> int:
    return len(connected_users)


def get_connected_users() -> dict:
    return connected_users

