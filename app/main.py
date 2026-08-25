from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import socketio

from app.database.connection import connect_db, close_db
from app.config.settings import settings
from app.services.socket_manager import sio

# ── Routers ──────────────────────────────────────────────────────────────────
from app.auth.router import router as auth_router
from app.modules.dealers.router import router as dealer_router
from app.modules.cars.router import router as cars_router
from app.modules.cars.upload_router import router as upload_router
from app.modules.cars.public_router import router as public_router
from app.modules.staff.router import router as staff_router
from app.modules.partners.router import router as partners_router
from app.modules.notifications.router import router as notifications_router
from app.modules.reports.router import router as reports_router
from app.modules.movements.router import router as movements_router
from app.modules.cctv.router import router as cctv_router
from app.modules.inventory.router import router as inventory_router
from app.modules.users.admin_router import router as admin_router
from app.modules.notifications.push_router import router as push_router
from app.modules.users.user_router import router as user_router
from app.modules.messages.router import router as messages_router
from app.services.socket_router import router as socket_router

try:
    from app.modules.follows.router import router as follows_router
    _has_follows = True
except Exception:
    try:
        from app.follows_router import router as follows_router
        _has_follows = True
    except Exception:
        _has_follows = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    try:
        from app.utils.comments_service import backfill_comment_counts
        await backfill_comment_counts()
    except Exception:
        # A backfill failure should never prevent the app from
        # starting - commentCount would just stay at whatever it
        # already was (0 or unset) for affected cars until the next
        # successful startup, not a reason to take the whole API down.
        pass
    yield
    await close_db()


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    description="Multi-Tenant Car Dealer Management SaaS API + Real-time Socket",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# ── Include all routers ───────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(dealer_router)
app.include_router(cars_router)
app.include_router(upload_router)
app.include_router(public_router)
app.include_router(staff_router)
app.include_router(partners_router)
app.include_router(notifications_router)
app.include_router(reports_router)
app.include_router(movements_router)
app.include_router(cctv_router)
app.include_router(inventory_router)
app.include_router(admin_router)
app.include_router(user_router)
app.include_router(push_router)
app.include_router(messages_router)
app.include_router(socket_router)
if _has_follows:
    app.include_router(follows_router)


# ── Health routes ─────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "message": f"{settings.APP_NAME} API + Socket is running",
        "version": "1.0.0",
        "status": "healthy",
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "app": settings.APP_NAME}


@app.get("/ping")
async def ping():
    return {"pong": True}


# ── Mount Socket.IO LAST (catches /socket.io/* path) ─────────────────────────
socket_app = socketio.ASGIApp(
    sio,
    other_asgi_app=app,
    socketio_path="/socket.io",
)
