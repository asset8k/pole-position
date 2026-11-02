import asyncio
import secrets
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

from pole_position.config import settings
from pole_position.database import engine

router = APIRouter()
KEEPALIVE_TIMEOUT_SECONDS = 8
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/internal/keepalive", include_in_schema=False)
async def keepalive(
    token: Annotated[str | None, Header(alias="X-Keepalive-Token")] = None,
) -> JSONResponse:
    expected = settings.keepalive_token.get_secret_value()
    # Bytes also handle malformed non-ASCII headers without a comparison error.
    if not expected.strip() or not token or not secrets.compare_digest(
        token.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="Forbidden", headers=NO_STORE)

    try:
        # Covers pool checkout, pre-ping/reconnect, SQL, and connection return.
        # Uses the same lazy engine / DATABASE_URL as application requests.
        async with asyncio.timeout(KEEPALIVE_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                result = await connection.execute(text("SELECT 1"))
                if result.scalar_one() != 1:
                    raise ValueError("Unexpected probe result")
    except Exception:
        # Never return/log connection strings, exception text, or the header.
        raise HTTPException(
            status_code=503, detail="Service unavailable", headers=NO_STORE
        ) from None

    return JSONResponse({"status": "ok", "database": "ok"}, headers=NO_STORE)
