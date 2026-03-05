"""Rate limiting 미들웨어 테스트."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.rate_limit import RateLimitMiddleware


client = TestClient(app)


def _reset_rate_limiter():
    """앱에 등록된 rate limiter 상태를 초기화한다."""
    for middleware in app.user_middleware:
        if middleware.cls is RateLimitMiddleware:
            break
    # middleware_stack에서 직접 찾아 reset
    stack = app.middleware_stack
    while stack is not None:
        if isinstance(stack, RateLimitMiddleware):
            stack.reset()
            return
        stack = getattr(stack, "app", None)


@pytest.fixture(autouse=True)
def _reset_limiter():
    """각 테스트 전 rate limiter 상태를 초기화한다."""
    _reset_rate_limiter()
    yield
    _reset_rate_limiter()


class TestRateLimitMiddleware:
    """Rate limiting 미들웨어 동작 검증."""

    def test_allows_requests_within_limit(self):
        """제한 내 요청은 허용된다."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_returns_429_when_exceeded(self):
        """전체 엔드포인트 제한(100 req/min) 초과 시 429를 반환한다."""
        for _ in range(100):
            resp = client.get("/health")
            assert resp.status_code == 200

        resp = client.get("/health")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert resp.json()["detail"] == "Too Many Requests"

    def test_post_jobs_strict_limit(self):
        """POST /api/jobs는 5 req/hour로 제한된다."""
        with patch("src.api.main.validate_youtube_url", return_value=True), \
             patch("src.api.main._executor") as mock_executor:
            mock_executor.submit.return_value = None

            for _ in range(5):
                resp = client.post(
                    "/api/jobs",
                    json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                )
                assert resp.status_code == 201

            resp = client.post(
                "/api/jobs",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            )
            assert resp.status_code == 429

    def test_retry_after_header_positive(self):
        """Retry-After 헤더는 양수여야 한다."""
        for _ in range(100):
            client.get("/health")

        resp = client.get("/health")
        assert resp.status_code == 429
        retry_after = int(resp.headers["Retry-After"])
        assert retry_after >= 1
