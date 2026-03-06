"""구조화된 로깅 및 글로벌 에러 핸들링 미들웨어 테스트."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.api.main import _job_store, app
from src.api.rate_limit import RateLimitMiddleware

client = TestClient(app, raise_server_exceptions=False)

_TEST_USER_ID = "test_user_mid"
_TEST_USERNAME = "midtestuser"
_TEST_PASSWORD = "Test1234!"


def _reset_rate_limiter():
    stack = app.middleware_stack
    while stack is not None:
        if isinstance(stack, RateLimitMiddleware):
            stack.reset()
            return
        stack = getattr(stack, "app", None)


@pytest.fixture(autouse=True)
def _setup():
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


def _get_auth_headers() -> dict[str, str]:
    resp = client.post(
        "/auth/login",
        data={"username": _TEST_USERNAME, "password": _TEST_PASSWORD},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestRequestIdHeader:
    """X-Request-ID 헤더 테스트."""

    def test_health_has_request_id(self):
        """헬스체크 응답에 X-Request-ID 헤더가 포함된다."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert "x-request-id" in resp.headers
        assert len(resp.headers["x-request-id"]) == 16

    def test_request_ids_are_unique(self):
        """각 요청마다 고유한 request_id가 부여된다."""
        ids = set()
        for _ in range(5):
            resp = client.get("/health")
            ids.add(resp.headers["x-request-id"])
        assert len(ids) == 5


class TestGlobalExceptionHandler:
    """글로벌 예외 핸들러 테스트."""

    @patch("src.api.dependencies._job_store")
    def test_unhandled_exception_returns_500(self, mock_store):
        """처리되지 않은 예외는 500과 일관된 에러 형식을 반환한다."""
        mock_store.get.side_effect = RuntimeError("unexpected error")
        headers = _get_auth_headers()
        resp = client.get("/api/jobs/aabbccddeeff", headers=headers)
        assert resp.status_code == 500
        data = resp.json()
        assert "detail" in data
        assert data["detail"] == "서버 내부 오류가 발생했습니다"
        assert "request_id" in data
