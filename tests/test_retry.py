"""Job 재시도 메커니즘 테스트."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.api.main import JobStatus, _job_store, app
from src.api.rate_limit import RateLimitMiddleware
from src.api.tasks import is_retryable_error

client = TestClient(app)

_TEST_USER_ID = "test_user_id1"
_TEST_USERNAME = "retryuser"
_TEST_PASSWORD = "testpass123"


def _reset_rate_limiter():
    stack = app.middleware_stack
    while stack is not None:
        if isinstance(stack, RateLimitMiddleware):
            stack.reset()
            return
        stack = getattr(stack, "app", None)


@pytest.fixture(autouse=True)
def _clear_jobs():
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


def _insert_job(job_id: str, **fields) -> None:
    defaults = {
        "status": JobStatus.failed,
        "url": "https://youtu.be/dQw4w9WgXcQ",
    }
    defaults.update(fields)
    _job_store.create(
        job_id,
        defaults["status"],
        defaults["url"],
        user_id=_TEST_USER_ID,
    )
    update_fields = {}
    if fields.get("error"):
        update_fields["error"] = fields["error"]
    if fields.get("retry_count") is not None:
        update_fields["retry_count"] = fields["retry_count"]
    if defaults["status"] != JobStatus.pending:
        update_fields["status"] = defaults["status"]
    if update_fields:
        _job_store.update(job_id, **update_fields)


class TestIsRetryableError:
    """재시도 가능 오류 분류 테스트."""

    def test_timeout_is_retryable(self):
        assert is_retryable_error(TimeoutError("Connection timed out"))

    def test_connection_refused_is_retryable(self):
        assert is_retryable_error(ConnectionError("Connection refused"))

    def test_http_503_is_retryable(self):
        assert is_retryable_error(Exception("HTTP Error 503: Service Unavailable"))

    def test_http_429_is_retryable(self):
        assert is_retryable_error(Exception("HTTP Error 429: Too Many Requests"))

    def test_network_unreachable_is_retryable(self):
        assert is_retryable_error(OSError("Network is unreachable"))

    def test_value_error_not_retryable(self):
        assert not is_retryable_error(ValueError("Invalid parameter"))

    def test_file_not_found_not_retryable(self):
        assert not is_retryable_error(FileNotFoundError("No such file"))

    def test_permission_error_not_retryable(self):
        assert not is_retryable_error(PermissionError("Access denied"))


class TestManualRetryEndpoint:
    """POST /api/jobs/{id}/retry 테스트."""

    @patch("src.api.main._enqueue_job")
    def test_retry_failed_job(self, mock_enqueue):
        """실패한 작업을 수동 재시도한다."""
        _insert_job("aabbccddeeff", error="some error", retry_count=2)
        headers = _get_auth_headers()

        resp = client.post("/api/jobs/aabbccddeeff/retry", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["retry_count"] == 0
        mock_enqueue.assert_called_once()

    def test_retry_non_failed_returns_409(self):
        """실패하지 않은 작업은 재시도할 수 없다."""
        _insert_job("aabbccddeeff", status=JobStatus.pending)
        headers = _get_auth_headers()

        resp = client.post("/api/jobs/aabbccddeeff/retry", headers=headers)
        assert resp.status_code == 409

    def test_retry_nonexistent_returns_404(self):
        """존재하지 않는 작업은 404를 반환한다."""
        headers = _get_auth_headers()
        resp = client.post("/api/jobs/aabbccddeeff/retry", headers=headers)
        assert resp.status_code == 404

    def test_retry_without_auth_returns_401(self):
        """인증 없이 재시도하면 401을 반환한다."""
        resp = client.post("/api/jobs/aabbccddeeff/retry")
        assert resp.status_code == 401


class TestJobResponseRetryCount:
    """JobResponse에 retry_count 포함 테스트."""

    def test_response_includes_retry_count(self):
        """응답에 retry_count가 포함된다."""
        _insert_job("aabbccddeeff", retry_count=2)
        headers = _get_auth_headers()

        resp = client.get("/api/jobs/aabbccddeeff", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["retry_count"] == 2

    def test_response_default_retry_count_zero(self):
        """retry_count 기본값은 0이다."""
        _insert_job("aabbccddeeff")
        headers = _get_auth_headers()

        resp = client.get("/api/jobs/aabbccddeeff", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["retry_count"] == 0


class TestRetryingStatus:
    """retrying 상태 테스트."""

    def test_retrying_status_in_enum(self):
        """retrying이 JobStatus enum에 포함된다."""
        assert JobStatus.retrying == "retrying"

    def test_cannot_delete_retrying_job(self):
        """retrying 상태의 작업은 삭제할 수 없다."""
        _insert_job("aabbccddeeff", status="retrying")
        headers = _get_auth_headers()

        resp = client.delete("/api/jobs/aabbccddeeff", headers=headers)
        assert resp.status_code == 409
