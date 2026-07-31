"""Cross-cutting HTTP middleware."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import settings


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id and timing to every response.

    The id is echoed in ``X-Request-ID`` and stored on ``request.state`` so
    audit entries written during the request can be correlated with the access
    log afterwards.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id

        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline security headers.

    The API serves JSON and uploaded files, never HTML, so the CSP is as tight
    as it can be: nothing may be loaded or embedded from an API response.
    HSTS is only sent in production, where TLS terminates in front of the app —
    sending it over plain HTTP in development would poison the browser cache.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._is_production = settings.ENVIRONMENT == "production"

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if self._is_production:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
