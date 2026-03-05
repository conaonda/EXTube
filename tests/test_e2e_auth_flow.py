"""인증 플로우 포함 E2E 테스트.

회원가입 → 로그인 → 토큰 획득 → Job 생성 → 상태 조회 전체 플로우 및
인증 실패 시나리오를 검증한다.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from src.api.config import get_settings
from src.api.main import _job_store, app
from src.api.rate_limit import RateLimitMiddleware

client = TestClient(app)

_settings = get_settings()


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
    yield
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()


class TestFullAuthFlow:
    """회원가입 → 로그인 → Job 생성 → 조회 전체 플로우."""

    @patch("src.api.main._enqueue_job")
    def test_register_login_create_get_job(self, mock_enqueue):
        """전체 인증 플로우가 정상 동작한다."""
        # 1. 회원가입
        reg = client.post(
            "/auth/register",
            json={"username": "e2euser", "password": "e2epass123"},
        )
        assert reg.status_code == 201
        assert "id" in reg.json()
        assert reg.json()["username"] == "e2euser"

        # 2. 로그인
        login = client.post(
            "/auth/login",
            data={"username": "e2euser", "password": "e2epass123"},
        )
        assert login.status_code == 200
        tokens = login.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        # 3. Job 생성
        create = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers=headers,
        )
        assert create.status_code == 201
        job_id = create.json()["id"]
        assert create.json()["status"] == "pending"

        # 4. Job 조회
        get = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert get.status_code == 200
        assert get.json()["id"] == job_id

        # 5. Job 목록 조회
        list_resp = client.get("/api/jobs", headers=headers)
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] >= 1

        # 6. Job 삭제
        delete = client.delete(f"/api/jobs/{job_id}", headers=headers)
        assert delete.status_code == 204

    @patch("src.api.main._enqueue_job")
    def test_refresh_then_access_job(self, mock_enqueue):
        """토큰 갱신 후에도 Job 접근이 가능하다."""
        # 회원가입 + 로그인
        client.post(
            "/auth/register",
            json={"username": "refreshuser", "password": "pass123456"},
        )
        login = client.post(
            "/auth/login",
            data={"username": "refreshuser", "password": "pass123456"},
        )
        tokens = login.json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        # Job 생성
        create = client.post(
            "/api/jobs",
            json={"url": "https://youtu.be/dQw4w9WgXcQ"},
            headers=headers,
        )
        job_id = create.json()["id"]

        # 토큰 갱신
        refresh = client.post(
            "/auth/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        assert refresh.status_code == 200
        new_tokens = refresh.json()
        new_headers = {
            "Authorization": f"Bearer {new_tokens['access_token']}"
        }

        # 새 토큰으로 Job 접근
        get = client.get(f"/api/jobs/{job_id}", headers=new_headers)
        assert get.status_code == 200
        assert get.json()["id"] == job_id


class TestInvalidTokenScenarios:
    """잘못된/만료된 토큰 시나리오."""

    def test_expired_access_token_returns_401(self):
        """만료된 access token은 401을 반환한다."""
        # 만료된 토큰 직접 생성
        payload = {
            "sub": "fake_user_id",
            "username": "fakeuser",
            "exp": time.time() - 100,  # 이미 만료
            "type": "access",
        }
        expired_token = jwt.encode(
            payload,
            _settings.jwt_secret_key,
            algorithm=_settings.jwt_algorithm,
        )
        headers = {"Authorization": f"Bearer {expired_token}"}
        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 401

    def test_malformed_token_returns_401(self):
        """잘못된 형식의 토큰은 401을 반환한다."""
        headers = {"Authorization": "Bearer not.a.valid.jwt.token"}
        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 401

    def test_missing_auth_header_returns_401(self):
        """인증 헤더 없이 보호된 엔드포인트 접근 시 401."""
        resp = client.get("/api/jobs")
        assert resp.status_code == 401

    def test_refresh_token_as_access_returns_401(self):
        """refresh token을 access token으로 사용하면 401."""
        client.post(
            "/auth/register",
            json={"username": "tokenuser", "password": "pass123456"},
        )
        login = client.post(
            "/auth/login",
            data={"username": "tokenuser", "password": "pass123456"},
        )
        refresh_token = login.json()["refresh_token"]
        headers = {"Authorization": f"Bearer {refresh_token}"}
        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 401

    def test_token_for_deleted_user_returns_401(self):
        """삭제된 사용자의 토큰은 401을 반환한다."""
        client.post(
            "/auth/register",
            json={"username": "deluser", "password": "pass123456"},
        )
        login = client.post(
            "/auth/login",
            data={"username": "deluser", "password": "pass123456"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 사용자 직접 삭제
        _job_store._conn.execute(
            "DELETE FROM users WHERE username = 'deluser'"
        )
        _job_store._conn.commit()

        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 401


class TestStreamAndSSEWithAuth:
    """인증이 적용된 SSE 스트리밍 테스트."""

    def test_stream_without_auth_returns_401(self):
        """인증 없이 SSE 스트리밍은 401."""
        resp = client.get("/api/jobs/aabbccddeeff/stream")
        assert resp.status_code == 401

    @patch("src.api.main._enqueue_job")
    def test_stream_with_auth_succeeds(self, mock_enqueue):
        """인증 후 SSE 스트리밍이 정상 동작한다."""
        client.post(
            "/auth/register",
            json={"username": "sseuser", "password": "pass123456"},
        )
        login = client.post(
            "/auth/login",
            data={"username": "sseuser", "password": "pass123456"},
        )
        headers = {
            "Authorization": f"Bearer {login.json()['access_token']}"
        }
        create = client.post(
            "/api/jobs",
            json={"url": "https://youtu.be/dQw4w9WgXcQ"},
            headers=headers,
        )
        job_id = create.json()["id"]
        # complete the job so SSE returns immediately
        _job_store.update(
            job_id,
            status="completed",
            result={"num_points3d": 10},
        )

        resp = client.get(
            f"/api/jobs/{job_id}/stream", headers=headers
        )
        assert resp.status_code == 200
        assert "completed" in resp.text


class TestCrossUserAccess:
    """사용자 간 리소스 접근 제어 E2E 테스트."""

    @patch("src.api.main._enqueue_job")
    def test_full_isolation_flow(self, mock_enqueue):
        """다른 사용자의 Job에 대한 조회/삭제/스트림이 모두 차단된다."""
        # 사용자 A 등록 + 로그인
        client.post(
            "/auth/register",
            json={"username": "alice", "password": "alicepass1"},
        )
        login_a = client.post(
            "/auth/login",
            data={"username": "alice", "password": "alicepass1"},
        )
        headers_a = {
            "Authorization": f"Bearer {login_a.json()['access_token']}"
        }

        # 사용자 B 등록 + 로그인
        client.post(
            "/auth/register",
            json={"username": "bob123", "password": "bobpass123"},
        )
        login_b = client.post(
            "/auth/login",
            data={"username": "bob123", "password": "bobpass123"},
        )
        headers_b = {
            "Authorization": f"Bearer {login_b.json()['access_token']}"
        }

        # Alice가 Job 생성
        create = client.post(
            "/api/jobs",
            json={"url": "https://youtu.be/dQw4w9WgXcQ"},
            headers=headers_a,
        )
        job_id = create.json()["id"]

        # Bob이 Alice의 Job에 접근 시도
        assert client.get(
            f"/api/jobs/{job_id}", headers=headers_b
        ).status_code == 403
        assert client.delete(
            f"/api/jobs/{job_id}", headers=headers_b
        ).status_code == 403
        assert client.get(
            f"/api/jobs/{job_id}/stream", headers=headers_b
        ).status_code == 403

        # Bob의 Job 목록에는 Alice의 Job이 없음
        bob_jobs = client.get("/api/jobs", headers=headers_b)
        assert bob_jobs.json()["total"] == 0

        # Alice는 자신의 Job에 접근 가능
        assert client.get(
            f"/api/jobs/{job_id}", headers=headers_a
        ).status_code == 200
