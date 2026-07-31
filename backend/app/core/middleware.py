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

    Two policies, because the application serves two very different things.

    Every API response gets ``default-src 'none'``: they carry JSON and
    uploaded files, so nothing in one should ever be loaded, executed or
    framed. That is as tight as a policy gets.

    The interactive documentation is the exception. It is HTML, and Swagger UI
    and ReDoc pull their script and stylesheet from a CDN — under the strict
    policy the browser blocks both and renders a blank page. Those two routes
    therefore get a policy wide enough to run, and no wider.

    HSTS is only sent in production, where TLS terminates in front of the app;
    sending it over plain HTTP in development would poison the browser cache.
    """

    #: Where FastAPI's documentation pages fetch their assets from. ReDoc also
    #: pulls a Google Fonts stylesheet, which in turn loads the font files from
    #: a second host — miss either and the page renders unstyled.
    DOCS_CDN = "https://cdn.jsdelivr.net"
    DOCS_FAVICON = "https://fastapi.tiangolo.com"
    DOCS_FONT_CSS = "https://fonts.googleapis.com"
    DOCS_FONT_FILES = "https://fonts.gstatic.com"

    #: ``'unsafe-inline'`` for scripts is unavoidable here: the HTML FastAPI
    #: generates bootstraps Swagger UI from an inline ``<script>`` block. It
    #: applies to the documentation pages alone, never to an API response.
    DOCS_CSP = (
        "default-src 'none'; "
        f"script-src 'self' 'unsafe-inline' {DOCS_CDN}; "
        f"style-src 'self' 'unsafe-inline' {DOCS_CDN} {DOCS_FONT_CSS}; "
        f"img-src 'self' data: {DOCS_FAVICON}; "
        f"font-src 'self' data: {DOCS_CDN} {DOCS_FONT_FILES}; "
        "connect-src 'self'; "
        "worker-src 'self' blob:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )

    STRICT_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

    def __init__(self, app: ASGIApp, doc_paths: set[str] | None = None) -> None:
        super().__init__(app)
        self._is_production = settings.ENVIRONMENT == "production"
        # Passed in by the caller rather than read off ``app``: middleware is
        # handed the next layer of the stack, not the FastAPI instance, so the
        # documentation URLs are not reachable from here. Supplying them
        # explicitly also means renaming or disabling a docs route cannot leave
        # a stale exemption behind.
        self._doc_paths = {path for path in (doc_paths or set()) if path}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        headers = response.headers

        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")

        is_docs = request.url.path in self._doc_paths
        headers.setdefault("Content-Security-Policy", self.DOCS_CSP if is_docs else self.STRICT_CSP)

        if self._is_production:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
