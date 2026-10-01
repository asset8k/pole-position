from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema

from pole_position.config import settings
from pole_position.database import Base, get_db
from pole_position.main import app


def get_test_database_url() -> str:
    """Refuse to run integration tests against an application database."""
    if not settings.test_database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")

    test_url = make_url(settings.test_database_url)
    app_url = make_url(settings.database_url)
    if (
        test_url.drivername != "postgresql+asyncpg"
        or not test_url.database
        or not test_url.database.endswith("_test")
        or test_url.database == app_url.database
    ):
        raise pytest.UsageError(
            "TEST_DATABASE_URL must use postgresql+asyncpg and a separate "
            "database whose name ends in '_test'."
        )

    return settings.test_database_url


@asynccontextmanager
async def isolated_test_session(database_url: str) -> AsyncIterator[AsyncSession]:
    """Keep test DDL and committed ORM writes inside one rollback boundary."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    schema_name = f"pytest_{uuid4().hex}"
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(CreateSchema(schema_name))
                await connection.execute(
                    text(f'SET LOCAL search_path TO "{schema_name}"')
                )
                await connection.run_sync(Base.metadata.create_all)
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    yield session
            finally:
                # Includes the temporary schema; never drops existing tables.
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def db_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, AsyncSession]]:
    database_url = get_test_database_url()
    monkeypatch.setattr(
        settings, "jwt_secret_key", SecretStr("auth-tests-only-secret-" * 4)
    )
    previous_overrides = app.dependency_overrides.copy()

    with TestClient(app) as test_client:
        # Async setup, requests, and teardown must share TestClient's event loop.
        assert test_client.portal is not None
        session_context = isolated_test_session(database_url)
        session = test_client.portal.call(session_context.__aenter__)

        async def override_get_db() -> AsyncIterator[AsyncSession]:
            yield session

        app.dependency_overrides[get_db] = override_get_db
        try:
            yield test_client, session
        finally:
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous_overrides)
            test_client.portal.call(session_context.__aexit__, None, None, None)
