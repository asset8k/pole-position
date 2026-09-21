from fastapi import FastAPI

app = FastAPI()


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
