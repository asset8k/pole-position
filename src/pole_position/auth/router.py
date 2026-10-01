from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from pole_position.auth.dependencies import require_current_user
from pole_position.auth.schemas import LoginRequest, RegisterRequest, TokenResponse
from pole_position.auth.service import login_user, register_user
from pole_position.database import get_db
from pole_position.users.model import User
from pole_position.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    db: Annotated[AsyncSession, Depends(get_db)],
    data: RegisterRequest,
):
    user = await register_user(db, data)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    db: Annotated[AsyncSession, Depends(get_db)],
    data: LoginRequest,
):
    token = await login_user(db, data)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


@router.get("/me", response_model=UserRead)
async def get_me(
    current_user: Annotated[User, Depends(require_current_user)],
) -> User:
    return current_user
