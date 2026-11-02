import ssl
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from pole_position.config import settings

DATABASE_CONNECT_TIMEOUT_SECONDS = 5
DATABASE_POOL_TIMEOUT_SECONDS = 5
DATABASE_COMMAND_TIMEOUT_SECONDS = 10


def database_connect_args() -> dict:
    # Production connections verify TLS certificates; local PostgreSQL can stay
    # unencrypted. Do not disable certificate verification to fix a connection.
    args: dict = {
        "timeout": DATABASE_CONNECT_TIMEOUT_SECONDS,
        "command_timeout": DATABASE_COMMAND_TIMEOUT_SECONDS,
    }
    if settings.database_ssl:
        args["ssl"] = ssl.create_default_context(cafile=settings.database_ssl_ca_file)
    return args


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_timeout=DATABASE_POOL_TIMEOUT_SECONDS,
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
