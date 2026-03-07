"""인증 플로우 및 작업 생명주기 통합 테스트.

단위 테스트와 달리, 여러 API 호출을 조합해
실제 사용 시나리오를 검증한다.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from src.api.auth import reset_login_attempts
from src.api.config import get_settings
from src.api.main import _job_store, app
from src.api.rate_limit import RateLimitMiddleware
from src.downloader import VideoMetadata

client = TestClient(app)
settings = get_settings()

_YT_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
_PASSWORD = "Test1234!"

_MOCK_META = VideoMetadata(
    duration=120,
    title="Test Video",
    video_id="dQw4w9WgXcQ",
    height=1080,
    filesize_approx=50 * 1024 * 1024,
)


def _reset_rate_limiter():
    stack = app.middleware_stack
    while stack is not None:
        if isinstance(stack, RateLimitMiddleware):
            stack.reset()
            return
        stack = getattr(stack, "app", None)


def _get_rate_limit() -> int:
    """미들웨어에 설정된 기본 rate limit(max_requests)를 반환한다."""
    stack = app.middleware_stack
    while stack is not None:
        if isinstance(stack, RateLimitMiddleware):
            return stack.default_rule.max_requests
        stack = getattr(stack, "app", None)
    return 100  # fallback


@pytest.fixture(autouse=True)
def _clear_db():
    _reset_rate_limiter()
    reset_login_attempts()
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()
    yield
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()


def _register(username="testuser"):
    return client.post(
        "/auth/register",
        json={"username": username, "password": _PASSWORD},
    )


def _login(username="testuser"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": _PASSWORD},
    )


def _headers(username="testuser"):
    _register(username)
    resp = _login(username)
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _create_job(headers):
    with (
        patch("src.api.routers.jobs._enqueue_job"),
        patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_META),
    ):
        return client.post(
            "/api/jobs",
            json={"url": _YT_URL, "force_reprocess": True},
            headers=headers,
        )


class TestAuthJobLifecycle:
    """등록 → 로그인 → 작업 생성 → 상태 조회 → 완료 → 결과 확인 전체 플로우."""

    def test_full_lifecycle(self):
        # 1. 등록
        resp = _register()
        assert resp.status_code == 201

        # 2. 로그인
        resp = _login()
        assert resp.status_code == 200
        tokens = resp.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        # 3. 작업 생성
        resp = _create_job(headers)
        assert resp.status_code == 201
        job_id = resp.json()["id"]
        assert resp.json()["status"] == "pending"

        # 4. 상태 조회
        resp = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

        # 5. 목록에 표시
        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["id"] == job_id

        # 6. DB에서 완료 처리 (파이프라인 시뮬레이션)
        _job_store.update(job_id, status="completed")

        # 7. 완료 상태 확인
        resp = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_failed_job_retry_lifecycle(self):
        headers = _headers()

        # 작업 생성
        resp = _create_job(headers)
        job_id = resp.json()["id"]

        # 실패 시뮬레이션
        _job_store.update(job_id, status="failed", error="COLMAP failed")

        resp = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert resp.json()["status"] == "failed"
        assert resp.json()["error"] == "COLMAP failed"

        # 재시도
        with patch("src.api.routers.jobs._enqueue_job"):
            resp = client.post(f"/api/jobs/{job_id}/retry", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"


class TestTokenExpiry:
    """토큰 만료 및 갱신 시나리오."""

    def test_expired_access_token_returns_401(self):
        _register()
        # 만료된 access token 생성
        expired_token = jwt.encode(
            {
                "sub": "test_id",
                "username": "testuser",
                "exp": time.time() - 10,
                "type": "access",
            },
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        headers = {"Authorization": f"Bearer {expired_token}"}
        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 401

    def test_refresh_then_access(self):
        """refresh token으로 새 access token을 발급받아 API에 접근한다."""
        _register()
        login_resp = _login()
        refresh_token = login_resp.json()["refresh_token"]

        # refresh
        resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        new_access = resp.json()["access_token"]

        # 새 token으로 접근
        headers = {"Authorization": f"Bearer {new_access}"}
        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 200

    def test_old_access_token_after_refresh_still_works(self):
        """refresh 후에도 아직 만료되지 않은 기존 access token은 유효하다."""
        _register()
        login_resp = _login()
        old_access = login_resp.json()["access_token"]
        refresh_token = login_resp.json()["refresh_token"]

        # refresh로 새 토큰 발급
        client.post("/auth/refresh", json={"refresh_token": refresh_token})

        # 기존 access token도 만료 전이면 유효
        headers = {"Authorization": f"Bearer {old_access}"}
        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 200

    def test_refresh_token_rotation_prevents_reuse(self):
        """사용한 refresh token은 재사용 불가 (token rotation)."""
        _register()
        login_resp = _login()
        refresh_token = login_resp.json()["refresh_token"]

        # 첫 번째 사용
        resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200

        # 동일 refresh token 재사용
        resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 401


class TestMaxJobsPerUser:
    """사용자별 동시 실행 제한 통합 테스트."""

    def test_limit_reached_then_freed(self):
        """제한 도달 후 작업 완료 시 새 작업 생성 가능."""
        headers = _headers()
        max_jobs = settings.max_jobs_per_user

        # 제한까지 작업 생성
        job_ids = []
        for _ in range(max_jobs):
            resp = _create_job(headers)
            assert resp.status_code == 201
            job_ids.append(resp.json()["id"])

        # 제한 초과
        resp = _create_job(headers)
        assert resp.status_code == 429

        # 하나 완료 처리
        _job_store.update(job_ids[0], status="completed")

        # 이제 새 작업 생성 가능
        resp = _create_job(headers)
        assert resp.status_code == 201

    def test_cancelled_job_frees_slot(self):
        """취소된 작업은 슬롯을 해제한다."""
        headers = _headers()
        max_jobs = settings.max_jobs_per_user

        job_ids = []
        for _ in range(max_jobs):
            resp = _create_job(headers)
            job_ids.append(resp.json()["id"])

        # 제한 초과 확인
        resp = _create_job(headers)
        assert resp.status_code == 429

        # 하나를 pending→cancelled
        _job_store.update(job_ids[0], status="cancelled")

        resp = _create_job(headers)
        assert resp.status_code == 201

    def test_different_users_have_separate_limits(self):
        """각 사용자는 독립적인 실행 제한을 갖는다."""
        headers_a = _headers("user_a")
        headers_b = _headers("user_b")

        # user_a가 제한까지 생성
        for _ in range(settings.max_jobs_per_user):
            resp = _create_job(headers_a)
            assert resp.status_code == 201

        # user_a는 제한 초과
        resp = _create_job(headers_a)
        assert resp.status_code == 429

        # user_b는 여전히 생성 가능
        resp = _create_job(headers_b)
        assert resp.status_code == 201


class TestRateLimitIntegration:
    """Rate limiting 통합 검증."""

    def test_rate_limit_returns_429_with_retry_after(self):
        """과도한 요청 시 429와 Retry-After 헤더를 반환한다."""
        rate_limit = _get_rate_limit()
        for _ in range(rate_limit):
            client.get("/health")

        resp = client.get("/health")
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert int(resp.headers["Retry-After"]) >= 1

    def test_authenticated_requests_share_rate_limit(self):
        """인증된 요청도 전체 rate limit에 포함된다."""
        headers = _headers()
        _reset_rate_limiter()  # _headers() 요청이 카운터를 오염시키지 않도록 재초기화

        rate_limit = _get_rate_limit()
        for _ in range(rate_limit):
            client.get("/api/jobs", headers=headers)

        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 429
