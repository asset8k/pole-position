from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pole_position.auth.schemas import LoginRequest, RegisterRequest, TokenResponse
from pole_position.auth.security import (
    create_access_token,
    hash_password,
    verify_access_token,
    verify_password,
)
from pole_position.chat.model import Conversation, Message  # noqa: F401
from pole_position.config import settings
from pole_position.users.model import User


async def register_user(db: AsyncSession, data: RegisterRequest) -> User | None:
    result = await db.execute(
        select(User).where(User.username == data.username),
    )
    if result.scalars().first():
        return None

    new_user = User(
        username=data.username,
        password_hash=hash_password(data.password),
    )
    db.add(new_user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()

        result = await db.execute(
            select(User).where(User.username == data.username),
        )
        if result.scalars().first() is not None:
            return None

        raise
    await db.refresh(new_user)
    return new_user


async def login_user(db: AsyncSession, data: LoginRequest) -> TokenResponse | None:
    result = await db.execute(
        select(User).where(User.username == data.username),
    )
    user = result.scalars().first()

    if not user or not verify_password(data.password, user.password_hash):
        return None

    # Create access token with user id as subject
    access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=access_token_expires,
    )
    return TokenResponse(access_token=access_token, token_type="bearer")


async def get_current_user(db: AsyncSession, token: str) -> User | None:
    user_id = verify_access_token(token)
    if user_id is None:
        return None

    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        return None

    result = await db.execute(
        select(User).where(User.id == user_id_int),
    )
    user = result.scalars().first()
    if not user:
        return None
    return user
