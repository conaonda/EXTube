"""JWT 인증 테스트."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.api.main import _job_store, app
from src.api.rate_limit import RateLimitMiddleware

client = TestClient(app)


def _reset_rate_limiter():
    stack = app.middleware_stack
    while stack is not None:
        if isinstance(stack, RateLimitMiddleware):
            stack.reset()
            return
        stack = getattr(stack, "app", None)


@pytest.fixture(autouse=True)
def _clear_db():
    """각 테스트 전후로 DB를 초기화한다."""
    _reset_rate_limiter()
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()
    yield
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()


def _register_user(username: str = "testuser", password: str = "testpass123"):
    return client.post(
        "/auth/register",
        json={"username": username, "password": password},
    )


def _login_user(username: str = "testuser", password: str = "testpass123"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )


def _auth_header(username: str = "testuser", password: str = "testpass123") -> dict:
    """사용자 등록+로그인 후 Authorization 헤더를 반환한다."""
    _register_user(username, password)
    resp = _login_user(username, password)
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestRegister:
    """POST /auth/register 테스트."""

    def test_register_success(self):
        resp = _register_user()
        assert resp.status_code == 201
        data = resp.json()
        assert data["username"] == "testuser"
        assert "id" in data

    def test_register_duplicate(self):
        _register_user()
        resp = _register_user()
        assert resp.status_code == 409

    def test_register_short_username(self):
        resp = _register_user(username="ab")
        assert resp.status_code == 422

    def test_register_short_password(self):
        resp = _register_user(password="short")
        assert resp.status_code == 422

    def test_register_invalid_username_chars(self):
        resp = _register_user(username="test user!")
        assert resp.status_code == 422


class TestLogin:
    """POST /auth/login 테스트."""

    def test_login_success(self):
        _register_user()
        resp = _login_user()
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self):
        _register_user()
        resp = _login_user(password="wrongpass")
        assert resp.status_code == 401

    def test_login_nonexistent_user(self):
        resp = _login_user(username="nouser")
        assert resp.status_code == 401


class TestRefresh:
    """POST /auth/refresh 테스트."""

    def test_refresh_success(self):
        _register_user()
        login_resp = _login_user()
        refresh_token = login_resp.json()["refresh_token"]

        resp = client.post(
            "/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    def test_refresh_reuse_revoked(self):
        """한 번 사용한 refresh token은 재사용 불가."""
        _register_user()
        login_resp = _login_user()
        refresh_token = login_resp.json()["refresh_token"]

        # 첫 번째 사용
        client.post("/auth/refresh", json={"refresh_token": refresh_token})
        # 두 번째 사용 — revoked
        resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 401

    def test_refresh_invalid_token(self):
        resp = client.post(
            "/auth/refresh",
            json={"refresh_token": "invalid.token.here"},
        )
        assert resp.status_code == 401


class TestProtectedEndpoints:
    """인증 보호 엔드포인트 테스트."""

    def test_create_job_without_auth_returns_401(self):
        resp = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert resp.status_code == 401

    def test_list_jobs_without_auth_returns_401(self):
        resp = client.get("/api/jobs")
        assert resp.status_code == 401

    def test_get_job_without_auth_returns_401(self):
        resp = client.get("/api/jobs/aabbccddeeff")
        assert resp.status_code == 401

    def test_delete_job_without_auth_returns_401(self):
        resp = client.delete("/api/jobs/aabbccddeeff")
        assert resp.status_code == 401

    def test_health_no_auth_required(self):
        resp = client.get("/health")
        assert resp.status_code == 200


class TestJobIsolation:
    """사용자별 Job 격리 테스트."""

    def test_user_cannot_see_other_users_job(self):
        from unittest.mock import patch

        headers_a = _auth_header("user_a", "password123")
        headers_b = _auth_header("user_b", "password456")

        from src.downloader import VideoMetadata

        _mock_meta = VideoMetadata(
            duration=120, title="Test", video_id="dQw4w9WgXcQ",
            height=1080, filesize_approx=50 * 1024 * 1024,
        )

        with patch("src.api.main._enqueue_job"), \
             patch("src.api.main.fetch_video_metadata", return_value=_mock_meta):
            resp = client.post(
                "/api/jobs",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                headers=headers_a,
            )
            job_id = resp.json()["id"]

        # user_b가 user_a의 job 접근 시도
        resp = client.get(f"/api/jobs/{job_id}", headers=headers_b)
        assert resp.status_code == 403

    def test_user_cannot_delete_other_users_job(self):
        from unittest.mock import patch
        from src.downloader import VideoMetadata

        headers_a = _auth_header("user_a", "password123")
        headers_b = _auth_header("user_b", "password456")

        _mock_meta = VideoMetadata(
            duration=120, title="Test", video_id="dQw4w9WgXcQ",
            height=1080, filesize_approx=50 * 1024 * 1024,
        )

        with patch("src.api.main._enqueue_job"), \
             patch("src.api.main.fetch_video_metadata", return_value=_mock_meta):
            resp = client.post(
                "/api/jobs",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                headers=headers_a,
            )
            job_id = resp.json()["id"]

        resp = client.delete(f"/api/jobs/{job_id}", headers=headers_b)
        assert resp.status_code == 403

    def test_list_jobs_only_shows_own(self):
        from unittest.mock import patch
        from src.downloader import VideoMetadata

        headers_a = _auth_header("user_a", "password123")
        headers_b = _auth_header("user_b", "password456")

        _mock_meta = VideoMetadata(
            duration=120, title="Test", video_id="dQw4w9WgXcQ",
            height=1080, filesize_approx=50 * 1024 * 1024,
        )

        with patch("src.api.main._enqueue_job"), \
             patch("src.api.main.fetch_video_metadata", return_value=_mock_meta):
            client.post(
                "/api/jobs",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                headers=headers_a,
            )
            client.post(
                "/api/jobs",
                json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                headers=headers_b,
            )

        resp = client.get("/api/jobs", headers=headers_a)
        assert resp.json()["total"] == 1

        resp = client.get("/api/jobs", headers=headers_b)
        assert resp.json()["total"] == 1
