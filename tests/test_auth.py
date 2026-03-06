"""JWT 인증 테스트."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.api.auth import _login_attempts
from src.api.main import _job_store, app
from src.api.rate_limit import RateLimitMiddleware

client = TestClient(app)

_DEFAULT_PASSWORD = "Test1234!"


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
    _login_attempts.clear()
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()
    yield
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()


def _register_user(username: str = "testuser", password: str = _DEFAULT_PASSWORD):
    return client.post(
        "/auth/register",
        json={"username": username, "password": password},
    )


def _login_user(username: str = "testuser", password: str = _DEFAULT_PASSWORD):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
    )


def _auth_header(username: str = "testuser", password: str = _DEFAULT_PASSWORD) -> dict:
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
        resp = _register_user(password="Short1!")
        assert resp.status_code == 422

    def test_register_weak_password_no_uppercase(self):
        resp = _register_user(password="testpass1!")
        assert resp.status_code == 422

    def test_register_weak_password_no_digit(self):
        resp = _register_user(password="Testpass!")
        assert resp.status_code == 422

    def test_register_weak_password_no_special(self):
        resp = _register_user(password="Testpass1")
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

        headers_a = _auth_header("user_a", "Password1!")
        headers_b = _auth_header("user_b", "Password2!")

        from src.downloader import VideoMetadata

        _mock_meta = VideoMetadata(
            duration=120, title="Test", video_id="dQw4w9WgXcQ",
            height=1080, filesize_approx=50 * 1024 * 1024,
        )

        with patch("src.api.routers.jobs._enqueue_job"), \
             patch("src.api.routers.jobs.fetch_video_metadata", return_value=_mock_meta):
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

        headers_a = _auth_header("user_a", "Password1!")
        headers_b = _auth_header("user_b", "Password2!")

        _mock_meta = VideoMetadata(
            duration=120, title="Test", video_id="dQw4w9WgXcQ",
            height=1080, filesize_approx=50 * 1024 * 1024,
        )

        with patch("src.api.routers.jobs._enqueue_job"), \
             patch("src.api.routers.jobs.fetch_video_metadata", return_value=_mock_meta):
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

        headers_a = _auth_header("user_a", "Password1!")
        headers_b = _auth_header("user_b", "Password2!")

        _mock_meta = VideoMetadata(
            duration=120, title="Test", video_id="dQw4w9WgXcQ",
            height=1080, filesize_approx=50 * 1024 * 1024,
        )

        with patch("src.api.routers.jobs._enqueue_job"), \
             patch("src.api.routers.jobs.fetch_video_metadata", return_value=_mock_meta):
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


class TestLoginLockout:
    """로그인 실패 횟수 제한 테스트."""

    def test_lockout_after_max_attempts(self):
        _register_user()
        for _ in range(5):
            resp = _login_user(password="WrongPass1!")
            assert resp.status_code == 401

        # 6번째 시도 — 잠금
        resp = _login_user(password="WrongPass1!")
        assert resp.status_code == 429
        assert "로그인 시도 횟수 초과" in resp.json()["detail"]

    def test_successful_login_resets_attempts(self):
        _register_user()
        for _ in range(3):
            _login_user(password="WrongPass1!")

        # 성공 로그인으로 카운터 초기화
        resp = _login_user()
        assert resp.status_code == 200

        # 다시 실패해도 카운터가 리셋되었으므로 잠금 안 됨
        for _ in range(3):
            _login_user(password="WrongPass1!")
        resp = _login_user()
        assert resp.status_code == 200

    def test_lockout_correct_password_still_blocked(self):
        _register_user()
        for _ in range(5):
            _login_user(password="WrongPass1!")

        # 올바른 비밀번호여도 잠금 상태
        resp = _login_user()
        assert resp.status_code == 429


class TestConfigValidation:
    """설정 검증 테스트."""

    def test_production_default_jwt_key_raises(self):
        from src.api.config import _DEFAULT_JWT_SECRET, Settings

        settings = Settings(
            environment="production",
            jwt_secret_key=_DEFAULT_JWT_SECRET,
        )
        with pytest.raises(RuntimeError, match="JWT 기본키"):
            settings.validate_production_settings()

    def test_production_cors_wildcard_raises(self):
        from src.api.config import Settings

        settings = Settings(
            environment="production",
            jwt_secret_key="a-secure-production-key-1234567890",
            cors_origins="*",
        )
        with pytest.raises(RuntimeError, match="CORS 와일드카드"):
            settings.validate_production_settings()

    def test_development_default_jwt_key_warns(self):
        import warnings

        from src.api.config import _DEFAULT_JWT_SECRET, Settings

        settings = Settings(
            environment="development",
            jwt_secret_key=_DEFAULT_JWT_SECRET,
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            settings.validate_production_settings()
            assert len(w) == 1
            assert "JWT 기본키" in str(w[0].message)

    def test_production_valid_settings_ok(self):
        from src.api.config import Settings

        settings = Settings(
            environment="production",
            jwt_secret_key="a-secure-production-key-1234567890",
            cors_origins="https://example.com",
        )
        settings.validate_production_settings()  # 예외 없음
