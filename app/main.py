from fastapi import FastAPI

print("MAIN.PY STARTING")

app = FastAPI()

print("FASTAPI CREATED")


@app.get("/")
async def root():
    return {"message": "working"}