"""Application entrypoint.

Run with ``uvicorn app.main:app``. The Docker image does exactly that after
applying migrations.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.v1.endpoints.health import API_VERSION
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.db.session import engine

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
)
logger = logging.getLogger("archeo")

DESCRIPTION = """
A centralised database for archaeological research and heritage management.

The API is the only component that talks to PostgreSQL; clients never reach the
database directly. Every endpoint below is authorised through the same policy:
a user's **global role** sets a ceiling, **project membership** grants access to
a project's contents, and **per-record grants** cover sharing outside the team.

### Roles

| Role | May |
|------|-----|
| `visitor` | browse public records, view the map, search |
| `student` | the above, plus create records and upload images in their projects; edit their own records |
| `researcher` | the above, plus create projects, edit project records, approve student submissions |
| `admin` | everything, including user management and system settings |

### Authentication

`POST /api/v1/auth/login` returns a short-lived **access token** and a
long-lived **refresh token**. Send the access token as
`Authorization: Bearer <token>`. When it expires, exchange the refresh token at
`POST /api/v1/auth/refresh` — the old refresh token is revoked in the process.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verify the database is usable before accepting traffic."""
    try:
        with engine.connect() as connection:
            postgis = connection.scalar(text("SELECT postgis_version()"))
        logger.info("Connected to PostgreSQL; PostGIS %s", postgis)
    except SQLAlchemyError as exc:
        # Do not abort: the readiness probe reports the failure, and the
        # container should stay up so an operator can inspect it.
        logger.error("Database unavailable at startup: %s", exc)
    yield
    engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=DESCRIPTION,
    version=API_VERSION,
    lifespan=lifespan,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    contact={"name": "Platform maintainers"},
    license_info={"name": "MIT"},
)

# Order matters: middleware added last runs first, so the request id is
# assigned before anything else can log or fail.
# The documentation routes need a looser content policy than API responses;
# see SecurityHeadersMiddleware. Their paths come from the app itself so the
# two cannot drift apart.
app.add_middleware(
    SecurityHeadersMiddleware,
    doc_paths={app.docs_url, app.redoc_url, app.swagger_ui_oauth2_redirect_url},
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time"],
)
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Report validation failures in a shape the frontend forms can consume."""
    errors = [
        {
            "field": ".".join(str(part) for part in error["loc"][1:]) or error["loc"][0],
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Validation failed", "code": "validation_error", "errors": errors},
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Turn constraint violations into 409s instead of 500s.

    The database message is not forwarded: it names tables and columns, which
    is more than a client needs to know.
    """
    logger.warning("Integrity error on %s %s: %s", request.method, request.url.path, exc.orig)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": "The change conflicts with an existing record",
            "code": "integrity_error",
        },
    )


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    logger.exception("Database error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "The database is temporarily unavailable", "code": "database_error"},
    )


app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["System"], summary="Service banner")
def root() -> dict[str, str]:
    return {
        "name": settings.PROJECT_NAME,
        "version": API_VERSION,
        "documentation": "/docs",
        "api": settings.API_V1_PREFIX,
    }
