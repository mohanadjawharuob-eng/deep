"""Security headers, and the content policy in particular.

The strict policy is right for API responses and fatal for the documentation
pages: Swagger UI and ReDoc load their script and stylesheet from a CDN, so
``default-src 'none'`` renders a blank page with a 200 status and no error the
user can see. These tests pin both halves of that.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

DOC_PATHS = ["/docs", "/redoc"]
API_PATHS = ["/api/v1/health", "/api/v1/projects", "/"]


def _policy(client: TestClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, f"{path} returned {response.status_code}"
    policy = response.headers.get("content-security-policy")
    assert policy, f"{path} carried no Content-Security-Policy"
    return policy


def _directive(policy: str, name: str) -> str:
    for part in policy.split(";"):
        part = part.strip()
        if part.startswith(f"{name} "):
            return part
    return ""


class TestApiResponses:
    @pytest.mark.parametrize("path", API_PATHS)
    def test_api_responses_forbid_everything(self, client: TestClient, path: str) -> None:
        policy = _policy(client, path)
        assert "default-src 'none'" in policy
        assert "script-src" not in policy, "an API response has no reason to allow scripts"
        assert "frame-ancestors 'none'" in policy

    @pytest.mark.parametrize("path", API_PATHS)
    def test_baseline_headers_are_present(self, client: TestClient, path: str) -> None:
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "no-referrer"


class TestDocumentationPages:
    @pytest.mark.parametrize("path", DOC_PATHS)
    def test_the_page_can_actually_load_what_it_references(
        self, client: TestClient, path: str
    ) -> None:
        """Every external asset in the HTML must be permitted by the policy
        served alongside it. This is the check that would have caught the blank
        documentation page."""
        response = client.get(path)
        policy = _policy(client, path)

        referenced = set(re.findall(r'(?:src|href)="(https?://[^"]+)"', response.text))
        assert referenced, f"{path} referenced no external assets; has FastAPI changed?"

        for url in referenced:
            origin = "/".join(url.split("/")[:3])
            assert origin in policy, (
                f"{path} loads {url} but its policy does not allow {origin}; "
                f"the browser will block it and render nothing"
            )

    @pytest.mark.parametrize("path", DOC_PATHS)
    def test_inline_bootstrap_script_is_permitted(self, client: TestClient, path: str) -> None:
        # FastAPI bootstraps both viewers from an inline <script> block.
        policy = _policy(client, path)
        assert "'unsafe-inline'" in _directive(policy, "script-src")

    @pytest.mark.parametrize("path", DOC_PATHS)
    def test_try_it_out_can_call_the_api(self, client: TestClient, path: str) -> None:
        # Without connect-src the "Try it out" button fails silently.
        assert "'self'" in _directive(_policy(client, path), "connect-src")

    @pytest.mark.parametrize("path", DOC_PATHS)
    def test_the_relaxation_goes_no_further_than_needed(
        self, client: TestClient, path: str
    ) -> None:
        policy = _policy(client, path)
        assert policy.startswith("default-src 'none'"), "the default must stay closed"
        assert "frame-ancestors 'none'" in policy, "docs must not be embeddable"
        assert "*" not in policy, "no wildcard source is acceptable, even here"

    def test_the_openapi_document_is_not_relaxed(self, client: TestClient) -> None:
        # It is JSON, fetched by the page; it needs no policy of its own.
        policy = _policy(client, "/api/v1/openapi.json")
        assert "script-src" not in policy
