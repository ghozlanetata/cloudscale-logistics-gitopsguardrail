"""HTTP API for the CloudScale Logistics shipment tracking service."""

import os
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel


class Shipment(BaseModel):
    id: str
    tracking_number: str
    status: str
    origin: str
    destination: str


SAMPLE_SHIPMENTS = [
    Shipment(
        id="shp-1001",
        tracking_number="CSL-2026-1001",
        status="in_transit",
        origin="Lagos",
        destination="Accra",
    ),
    Shipment(
        id="shp-1002",
        tracking_number="CSL-2026-1002",
        status="delivered",
        origin="Abuja",
        destination="Kano",
    ),
]


def database_ready(database_url: str | None) -> bool:
    """Check the configured PostgreSQL dependency without leaking connection details."""
    if not database_url:
        return True  # Local/demo mode uses the deterministic sample catalog.
    try:
        with psycopg.connect(database_url, connect_timeout=2) as connection:
            connection.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.database_url = os.getenv("DATABASE_URL")
    application.state.environment = os.getenv("APP_ENV", "development")
    yield


app = FastAPI(title="CloudScale Logistics API", version="1.0.0", lifespan=lifespan)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    """Process health only; Kubernetes uses this for liveness."""
    return {"status": "ok"}


@app.get("/ready", include_in_schema=False)
def ready(request: Request) -> dict[str, str]:
    """Readiness includes the configured data dependency."""
    database_url = getattr(request.app.state, "database_url", None)
    environment = getattr(request.app.state, "environment", "development")
    if (environment == "production" and not database_url) or not database_ready(database_url):
        raise HTTPException(status_code=503, detail="service dependency unavailable")
    return {"status": "ready"}


@app.get("/api/shipments", response_model=list[Shipment])
def list_shipments() -> list[Shipment]:
    return SAMPLE_SHIPMENTS


@app.get("/api/shipments/{shipment_id}", response_model=Shipment)
def get_shipment(shipment_id: str) -> Shipment:
    for shipment in SAMPLE_SHIPMENTS:
        if shipment.id == shipment_id:
            return shipment
    raise HTTPException(status_code=404, detail="shipment not found")
