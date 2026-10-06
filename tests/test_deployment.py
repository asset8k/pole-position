import ssl
from types import SimpleNamespace

from fastapi.testclient import TestClient

from pole_position import main
from pole_position.config import settings
from pole_position.database import database_connect_args


def test_production_cors_allows_only_configured_origin(monkeypatch):
    monkeypatch.setattr(settings, "cors_origins", "https://pole-position.vercel.app")
    monkeypatch.setattr(settings, "validate_corpus_on_startup", False)
    with TestClient(main.create_app()) as client:
        headers = {
            "Origin": "https://pole-position.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        }
        response = client.options("/api/chat", headers=headers)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == headers["Origin"]
        headers["Origin"] = "https://untrusted.example"
        response = client.options("/api/chat", headers=headers)
        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers


def test_readiness_checks_corpus_without_model_calls(monkeypatch):
    monkeypatch.setattr(settings, "validate_corpus_on_startup", False)
    monkeypatch.setattr(main, "get_sparse_corpus", lambda: SimpleNamespace(index=SimpleNamespace(chunk_count=2857)))
    with TestClient(main.create_app()) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/ready").json() == {"status": "ok", "active_chunks": 2857}


def test_missing_corpus_is_not_ready(monkeypatch):
    monkeypatch.setattr(settings, "validate_corpus_on_startup", False)

    def missing():
        raise FileNotFoundError("private server path")

    monkeypatch.setattr(main, "get_sparse_corpus", missing)
    with TestClient(main.create_app()) as client:
        response = client.get("/api/ready")
        assert response.status_code == 503
        assert "private server path" not in response.text


def test_database_tls_verifies_certificates(monkeypatch):
    monkeypatch.setattr(settings, "database_ssl", True)
    monkeypatch.setattr(settings, "database_ssl_ca_file", None)
    context = database_connect_args()["ssl"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    monkeypatch.setattr(settings, "database_ssl", False)
    assert database_connect_args() == {}


def test_database_tls_accepts_the_official_supabase_ca(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(settings, "database_ssl", True)
    monkeypatch.setattr(
        settings, "database_ssl_ca_file",
        Path(__file__).resolve().parents[1] / "data/certificates/supabase-ca.crt",
    )
    context = database_connect_args()["ssl"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert context.cert_store_stats()["x509_ca"] >= 1
