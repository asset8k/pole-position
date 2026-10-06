import ssl
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from pole_position.config import settings


def database_connect_args() -> dict:
    # Production connections verify TLS certificates; local PostgreSQL can stay
    # unencrypted. Do not disable certificate verification to fix a connection.
    if not settings.database_ssl:
        return {}
    return {"ssl": ssl.create_default_context(cafile=settings.database_ssl_ca_file)}


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=database_connect_args(),
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
