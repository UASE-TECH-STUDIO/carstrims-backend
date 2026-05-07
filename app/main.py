from fastapi import FastAPI
from contextlib import asynccontextmanager

print("STEP 1")

from app.database.connection import connect_db, close_db

print("STEP 2")

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("STEP 3 - CONNECTING DB")

    try:
        await connect_db()
        print("STEP 4 - DB CONNECTED")
    except Exception as e:
        print("DB ERROR:", str(e))

    yield

    print("STEP 5 - CLOSING DB")

    try:
        await close_db()
    except Exception as e:
        print("CLOSE DB ERROR:", str(e))


app = FastAPI(lifespan=lifespan)

print("STEP 6")


@app.get("/")
async def root():
    return {"message": "working"}