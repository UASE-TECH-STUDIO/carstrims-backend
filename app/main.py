from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database.connection import connect_db, close_db
from app.config.settings import settings
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
from app.modules.users.user_router import router as user_router
from app.modules.messages.router import router as messages_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    yield
    await close_db()


app = FastAPI(
    title=settings.APP_NAME,
    description="Multi-Tenant Car Dealer Management SaaS API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
app.include_router(messages_router)


@app.get("/")
async def root():
    return {"message": f"{settings.APP_NAME} API is running", "version": "1.0.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}

