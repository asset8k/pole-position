from fastapi import FastAPI

from pole_position.auth.router import router as auth_router
from pole_position.chat.router import router as chat_router

app = FastAPI()
app.include_router(chat_router)
app.include_router(auth_router, prefix="/api")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
