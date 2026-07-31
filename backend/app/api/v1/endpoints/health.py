"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DbSession
from app.core.config import settings

router = APIRouter(tags=["System"])

#: Bumped on each release; also reported in the OpenAPI document.
API_VERSION = "0.1.0"


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str


class ReadinessResponse(BaseModel):
    status: str
    database: str
    postgis: str | None = None
    detail: str | None = None


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    """Answers as long as the process is up; does not touch the database."""
    return HealthResponse(status="ok", environment=settings.ENVIRONMENT, version=API_VERSION)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description=(
        "Verifies the database is reachable and PostGIS is installed. Returns "
        "503 when it is not, so orchestrators hold traffic back."
    ),
)
def ready(session: DbSession, response: Response) -> ReadinessResponse:
    try:
        session.execute(text("SELECT 1"))
        postgis_version = session.scalar(text("SELECT postgis_version()"))
    except SQLAlchemyError as exc:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="unavailable", database="unreachable", detail=type(exc).__name__
        )
    return ReadinessResponse(status="ok", database="ok", postgis=postgis_version)
