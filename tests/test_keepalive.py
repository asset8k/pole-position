import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from pole_position import main, monitoring
from pole_position.config import settings

TOKEN = "pole-position-monitoring-test-only"
PATH = "/internal/keepalive"
HEADERS = {"X-Keepalive-Token": TOKEN}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "keepalive_token", SecretStr(TOKEN))
    monkeypatch.setattr(settings, "validate_corpus_on_startup", False)
    with TestClient(main.create_app()) as test_client:
        yield test_client


@pytest.fixture
def database(monkeypatch):
    result = SimpleNamespace(scalar_one=Mock(return_value=1))
    connection = SimpleNamespace(execute=AsyncMock(return_value=result))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=connection)
    context.__aexit__ = AsyncMock(return_value=False)
    fake_engine = SimpleNamespace(connect=Mock(return_value=context))
    monkeypatch.setattr(monitoring, "engine", fake_engine)
    return SimpleNamespace(engine=fake_engine, context=context, connection=connection, result=result)


@pytest.mark.parametrize("supplied", [None, "", "wrong", TOKEN + "suffix"])
def test_invalid_token_is_forbidden_without_database_access(client, database, supplied):
    response = client.get(PATH, headers={} if supplied is None else {"X-Keepalive-Token": supplied})
    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}
    assert response.headers["Cache-Control"] == "no-store"
    database.engine.connect.assert_not_called()


@pytest.mark.parametrize("configured", ["", "   "])
def test_unconfigured_token_fails_closed(client, database, monkeypatch, configured):
    monkeypatch.setattr(settings, "keepalive_token", SecretStr(configured))
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store"
    database.engine.connect.assert_not_called()


def test_query_string_or_bearer_token_cannot_authenticate(client, database):
    response = client.get(PATH, params={"token": TOKEN}, headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 403
    database.engine.connect.assert_not_called()


def test_non_ascii_configured_token_does_not_cause_a_500(client, database, monkeypatch):
    monkeypatch.setattr(settings, "keepalive_token", SecretStr(TOKEN + "\u00f1"))
    assert client.get(PATH, headers=HEADERS).status_code == 403
    database.engine.connect.assert_not_called()


def test_authenticated_probe_runs_only_select_one_and_releases_connection(client, database, monkeypatch):
    compare = Mock(wraps=monitoring.secrets.compare_digest)
    monkeypatch.setattr(monitoring.secrets, "compare_digest", compare)
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert response.headers["Cache-Control"] == "no-store"
    compare.assert_called_once_with(TOKEN.encode(), TOKEN.encode())
    database.connection.execute.assert_awaited_once()
    assert str(database.connection.execute.call_args.args[0]) == "SELECT 1"
    database.context.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("phase", ["acquire", "query", "release"])
def test_database_errors_are_generic_503_and_not_logged(client, database, caplog, phase):
    error = OperationalError("private SQL", {}, Exception("private database credential"))
    operation = {"acquire": database.context.__aenter__, "query": database.connection.execute,
                 "release": database.context.__aexit__}[phase]
    operation.side_effect = error
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}
    assert response.headers["Cache-Control"] == "no-store"
    assert "private" not in response.text + caplog.text
    assert TOKEN not in response.text + caplog.text


@pytest.mark.parametrize("phase", ["acquire", "query", "release"])
def test_total_deadline_bounds_database_operations(client, database, monkeypatch, phase):
    monkeypatch.setattr(monitoring, "KEEPALIVE_TIMEOUT_SECONDS", 0.02)

    async def stalled(*_args):
        await asyncio.Event().wait()

    operation = {"acquire": database.context.__aenter__, "query": database.connection.execute,
                 "release": database.context.__aexit__}[phase]
    operation.side_effect = stalled
    started = time.monotonic()
    response = client.get(PATH, headers=HEADERS)
    assert time.monotonic() - started < 2
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}
    assert response.headers["Cache-Control"] == "no-store"


def test_unsuccessful_sql_result_is_not_healthy(client, database):
    database.result.scalar_one.return_value = None
    assert client.get(PATH, headers=HEADERS).status_code == 503


def test_probe_can_recover_after_a_database_failure(client, database):
    database.connection.execute.side_effect = [OSError("connection closed"), database.result]
    assert client.get(PATH, headers=HEADERS).status_code == 503
    assert client.get(PATH, headers=HEADERS).status_code == 200


def test_public_health_is_unchanged_and_probe_is_get_only(client, database):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.post(PATH, headers=HEADERS).status_code == 405
    assert PATH not in client.get("/openapi.json").json()["paths"]
    database.engine.connect.assert_not_called()


def test_startup_does_not_probe_database_or_load_corpus_by_default(monkeypatch):
    monkeypatch.setattr(settings, "validate_corpus_on_startup", False)
    lazy_engine = SimpleNamespace(connect=Mock(), dispose=AsyncMock())
    corpus = Mock(side_effect=AssertionError("Unexpected startup work"))
    monkeypatch.setattr(main, "engine", lazy_engine)
    monkeypatch.setattr(monitoring, "engine", lazy_engine)
    monkeypatch.setattr(main, "get_sparse_corpus", corpus)
    with TestClient(main.create_app()) as test_client:
        assert test_client.get("/api/health").status_code == 200
    lazy_engine.connect.assert_not_called()
    lazy_engine.dispose.assert_awaited_once()
    corpus.assert_not_called()


def test_probe_executes_real_sql_on_isolated_test_database(db_client, monkeypatch):
    # db_client already enforces a separate *_test database, never DATABASE_URL.
    test_client, _session = db_client
    monkeypatch.setattr(settings, "keepalive_token", SecretStr(TOKEN))
    assert settings.test_database_url is not None
    test_engine = create_async_engine(
        settings.test_database_url,
        poolclass=NullPool,
        connect_args={"timeout": 5, "command_timeout": 5},
    )
    statements = []

    @event.listens_for(test_engine.sync_engine, "before_cursor_execute")
    def record_statement(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    monkeypatch.setattr(monitoring, "engine", test_engine)
    try:
        response = test_client.get(PATH, headers=HEADERS)
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "ok"}
        assert statements == ["SELECT 1"]
    finally:
        assert test_client.portal is not None
        test_client.portal.call(test_engine.dispose)
