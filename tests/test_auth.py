from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pole_position.auth.security import (
    create_access_token,
    verify_access_token,
    verify_password,
)
from pole_position.users.model import User


@pytest.fixture
def client(db_client: tuple[TestClient, AsyncSession]) -> TestClient:
    return db_client[0]


@pytest.fixture
def registered_user(client: TestClient) -> dict[str, str]:
    credentials = {"username": "assetk", "password": "securepassword123"}
    response = client.post("/api/auth/register", json=credentials)
    assert response.status_code == 201
    return credentials


@pytest.fixture
def access_token(client: TestClient, registered_user: dict[str, str]) -> str:
    response = client.post("/api/auth/login", json=registered_user)
    assert response.status_code == 200
    return response.json()["access_token"]


def test_register_user(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={"username": "assetk", "password": "securepassword123"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "assetk"
    assert isinstance(body["id"], int)
    assert body["created_at"]
    assert set(body) == {"id", "username", "created_at"}


def test_registration_stores_a_password_hash(
    db_client: tuple[TestClient, AsyncSession],
    registered_user: dict[str, str],
) -> None:
    test_client, session = db_client
    assert test_client.portal is not None
    user = test_client.portal.call(
        session.scalar, select(User).where(User.username == registered_user["username"])
    )
    assert user is not None
    assert user.password_hash != registered_user["password"]
    assert verify_password(registered_user["password"], user.password_hash)
    assert not verify_password("wrong-password", user.password_hash)


def test_duplicate_username(
    client: TestClient, registered_user: dict[str, str]
) -> None:
    response = client.post("/api/auth/register", json=registered_user)
    assert response.status_code == 409
    assert response.json()["detail"] == "Username already exists"


def test_login_user(client: TestClient, registered_user: dict[str, str]) -> None:
    response = client.post("/api/auth/login", json=registered_user)
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    assert verify_access_token(body["access_token"]) is not None


def test_login_wrong_password(
    client: TestClient, registered_user: dict[str, str]
) -> None:
    response = client.post(
        "/api/auth/login", json={**registered_user, "password": "wrongpassword123"}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_login_unknown_username(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": "irmao", "password": "securepassword123"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"


def test_get_current_user_without_token(client: TestClient) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_get_current_user_with_valid_token(
    client: TestClient, registered_user: dict[str, str], access_token: str
) -> None:
    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == registered_user["username"]
    assert str(body["id"]) == verify_access_token(access_token)
    assert body["created_at"]
    assert set(body) == {"id", "username", "created_at"}


def test_get_current_user_with_invalid_token(client: TestClient) -> None:
    response = client.get(
        "/api/auth/me", headers={"Authorization": "Bearer not-a-valid-jwt"}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_get_current_user_with_expired_token(
    client: TestClient, access_token: str
) -> None:
    user_id = verify_access_token(access_token)
    expired_token = create_access_token(
        {"sub": user_id}, expires_delta=timedelta(seconds=-1)
    )
    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize("subject", [None, "not-an-integer", "999999"])
def test_get_current_user_rejects_invalid_or_unknown_subject(
    client: TestClient, subject: str | None
) -> None:
    token = create_access_token({} if subject is None else {"sub": subject})
    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "ab", "password": "securepassword123"},
        {"username": "a" * 51, "password": "securepassword123"},
        {"username": "AssetK", "password": "securepassword123"},
        {"username": "asset-k", "password": "securepassword123"},
        {"username": "assetk", "password": "short"},
        {"username": "assetk"},
        {"password": "securepassword123"},
    ],
)
def test_register_rejects_invalid_input(
    client: TestClient, payload: dict[str, str]
) -> None:
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 422
