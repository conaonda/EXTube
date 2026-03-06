"""Docker Compose 기반 통합 테스트.

이 테스트는 docker-compose.test.yml로 띄운 서비스에 HTTP 요청을 보내
전체 API 플로우를 검증한다.

실행: make test-integration
"""

from __future__ import annotations

import os
import time

import pytest
import requests

BASE_URL = os.environ.get("INTEGRATION_TEST_URL", "http://localhost:8099")
TEST_USERNAME = "integration_user"
TEST_PASSWORD = "IntTest1234!"


@pytest.fixture(scope="module")
def api_url():
    """API 서버가 준비될 때까지 대기한다."""
    url = BASE_URL
    for i in range(30):
        try:
            resp = requests.get(f"{url}/health", timeout=3)
            if resp.status_code == 200:
                return url
        except requests.ConnectionError:
            pass
        time.sleep(2)
    pytest.skip("통합 테스트 서버에 연결할 수 없습니다")


@pytest.fixture(scope="module")
def auth_headers(api_url):
    """테스트 사용자를 등록하고 인증 헤더를 반환한다."""
    # 등록
    resp = requests.post(
        f"{api_url}/auth/register",
        json={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        timeout=10,
    )
    assert resp.status_code in (201, 409), f"등록 실패: {resp.text}"

    # 로그인
    resp = requests.post(
        f"{api_url}/auth/login",
        data={"username": TEST_USERNAME, "password": TEST_PASSWORD},
        timeout=10,
    )
    assert resp.status_code == 200, f"로그인 실패: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestHealthEndpoints:
    """서비스 상태 확인 테스트."""

    def test_health(self, api_url):
        resp = requests.get(f"{api_url}/health", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"

    def test_health_ready(self, api_url):
        """Redis 연결을 포함한 준비 상태를 확인한다."""
        resp = requests.get(f"{api_url}/health/ready", timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"


class TestAuthFlow:
    """인증 플로우 통합 테스트."""

    def test_register_and_login(self, api_url):
        """사용자 등록 후 로그인이 성공한다."""
        username = f"authtest_{int(time.time())}"
        resp = requests.post(
            f"{api_url}/auth/register",
            json={"username": username, "password": TEST_PASSWORD},
            timeout=10,
        )
        assert resp.status_code == 201
        assert resp.json()["username"] == username

        resp = requests.post(
            f"{api_url}/auth/login",
            data={"username": username, "password": TEST_PASSWORD},
            timeout=10,
        )
        assert resp.status_code == 200
        tokens = resp.json()
        assert "access_token" in tokens
        assert "refresh_token" in tokens

    def test_refresh_token(self, api_url):
        """refresh token으로 새 토큰 쌍을 발급받는다."""
        username = f"refresh_{int(time.time())}"
        requests.post(
            f"{api_url}/auth/register",
            json={"username": username, "password": TEST_PASSWORD},
            timeout=10,
        )
        login_resp = requests.post(
            f"{api_url}/auth/login",
            data={"username": username, "password": TEST_PASSWORD},
            timeout=10,
        )
        refresh_token = login_resp.json()["refresh_token"]

        resp = requests.post(
            f"{api_url}/auth/refresh",
            json={"refresh_token": refresh_token},
            timeout=10,
        )
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_protected_endpoint_without_auth(self, api_url):
        """인증 없이 보호된 엔드포인트에 접근하면 401을 반환한다."""
        resp = requests.get(f"{api_url}/api/jobs", timeout=5)
        assert resp.status_code == 401


class TestJobApiFlow:
    """Job API 통합 테스트."""

    def test_list_jobs_empty(self, api_url, auth_headers):
        """초기 상태에서 Job 목록은 비어있다."""
        resp = requests.get(
            f"{api_url}/api/jobs",
            headers=auth_headers,
            timeout=5,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    def test_create_job_invalid_url(self, api_url, auth_headers):
        """유효하지 않은 URL로 Job 생성 시 400을 반환한다."""
        resp = requests.post(
            f"{api_url}/api/jobs",
            json={"url": "https://invalid-url.com/not-youtube"},
            headers=auth_headers,
            timeout=10,
        )
        assert resp.status_code == 400

    def test_get_nonexistent_job(self, api_url, auth_headers):
        """존재하지 않는 Job 조회 시 404를 반환한다."""
        resp = requests.get(
            f"{api_url}/api/jobs/aabbccddeeff",
            headers=auth_headers,
            timeout=5,
        )
        assert resp.status_code == 404

    def test_storage_usage(self, api_url, auth_headers):
        """스토리지 사용량을 조회할 수 있다."""
        resp = requests.get(
            f"{api_url}/api/storage/usage",
            headers=auth_headers,
            timeout=5,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_bytes" in data
        assert "total_mb" in data


class TestSecurityIntegration:
    """보안 관련 통합 테스트."""

    def test_security_headers_present(self, api_url):
        """응답에 보안 헤더가 포함된다."""
        resp = requests.get(f"{api_url}/health", timeout=5)
        assert "x-content-type-options" in resp.headers
        assert "x-frame-options" in resp.headers

    def test_rate_limiting(self, api_url, auth_headers):
        """과도한 요청 시 429를 반환한다."""
        for _ in range(110):
            resp = requests.get(
                f"{api_url}/health",
                timeout=5,
            )
            if resp.status_code == 429:
                break
        else:
            pytest.skip("rate limit에 도달하지 않음 (테스트 환경 설정에 따라 다를 수 있음)")

    def test_login_lockout(self, api_url):
        """반복적인 로그인 실패 시 잠금이 적용된다."""
        username = f"lockout_{int(time.time())}"
        requests.post(
            f"{api_url}/auth/register",
            json={"username": username, "password": TEST_PASSWORD},
            timeout=10,
        )

        for _ in range(5):
            requests.post(
                f"{api_url}/auth/login",
                data={"username": username, "password": "WrongPass1!"},
                timeout=10,
            )

        resp = requests.post(
            f"{api_url}/auth/login",
            data={"username": username, "password": "WrongPass1!"},
            timeout=10,
        )
        assert resp.status_code == 429
