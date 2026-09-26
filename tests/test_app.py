from fastapi.testclient import TestClient

from app import main
from app.main import app


def test_health_and_ready():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").json() == {"status": "ready"}


def test_shipments_list_and_lookup():
    with TestClient(app) as client:
        response = client.get("/api/shipments")
        assert response.status_code == 200
        assert response.json()[0]["id"] == "shp-1001"
        assert client.get("/api/shipments/shp-1001").json()["status"] == "in_transit"


def test_missing_shipment_returns_404():
    with TestClient(app) as client:
        response = client.get("/api/shipments/missing")
        assert response.status_code == 404
        assert response.json()["detail"] == "shipment not found"


def test_readiness_returns_503_when_database_is_unavailable(monkeypatch):
    monkeypatch.setattr(main, "database_ready", lambda _database_url: False)
    with TestClient(app) as client:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["detail"] == "service dependency unavailable"


def test_production_readiness_fails_closed_without_database_url(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with TestClient(app) as client:
        response = client.get("/ready")
        assert response.status_code == 503
