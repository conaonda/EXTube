"""보안 헤더 및 CORS 정책 테스트."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.api.main import _job_store, app
from src.api.rate_limit import RateLimitMiddleware

client = TestClient(app)

_TEST_USER_ID = "test_user_id1"
_TEST_USERNAME = "securityuser"
_TEST_PASSWORD = "Test1234!"


def _reset_rate_limiter():
    stack = app.middleware_stack
    while stack is not None:
        if isinstance(stack, RateLimitMiddleware):
            stack.reset()
            return
        stack = getattr(stack, "app", None)


@pytest.fixture(autouse=True)
def _clear_db():
    _reset_rate_limiter()
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()
    from passlib.context import CryptContext

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    _job_store.users.create(_TEST_USER_ID, _TEST_USERNAME, pwd.hash(_TEST_PASSWORD))
    yield
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()


class TestSecurityHeaders:
    """보안 헤더 적용 테스트."""

    def test_x_content_type_options(self):
        resp = client.get("/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options(self):
        resp = client.get("/health")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_x_xss_protection(self):
        resp = client.get("/health")
        assert resp.headers.get("x-xss-protection") == "0"

    def test_referrer_policy(self):
        resp = client.get("/health")
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self):
        resp = client.get("/health")
        assert "camera=()" in resp.headers.get("permissions-policy", "")

    def test_request_id_header(self):
        resp = client.get("/health")
        assert resp.headers.get("x-request-id") is not None


class TestCORSPolicy:
    """CORS 정책 테스트."""

    def test_allowed_origin(self):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert (
            resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
        )

    def test_disallowed_origin(self):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") is None

    def test_allowed_methods_restricted(self):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        methods = resp.headers.get("access-control-allow-methods", "")
        assert "GET" in methods

    def test_allowed_headers_restricted(self):
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        headers_val = resp.headers.get("access-control-allow-headers", "")
        assert "authorization" in headers_val.lower()


class TestSecurityHeadersMiddleware:
    """SecurityHeadersMiddleware 단위 테스트."""

    def test_production_includes_hsts(self):
        from src.api.middleware import SecurityHeadersMiddleware

        async def dummy_app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                }
            )
            await send({"type": "http.response.body", "body": b""})

        mw = SecurityHeadersMiddleware(dummy_app, environment="production")
        header_names = [h[0] for h in mw._headers]
        assert b"strict-transport-security" in header_names
        assert b"content-security-policy" in header_names

    def test_development_excludes_hsts(self):
        from src.api.middleware import SecurityHeadersMiddleware

        async def dummy_app(scope, receive, send):
            pass

        mw = SecurityHeadersMiddleware(dummy_app, environment="development")
        header_names = [h[0] for h in mw._headers]
        assert b"strict-transport-security" not in header_names
        assert b"content-security-policy" not in header_names
