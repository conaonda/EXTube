"""FastAPI API 테스트."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.api.main import _job_store, app
from src.api.rate_limit import RateLimitMiddleware
from src.api.routers.jobs import JobStatus
from src.downloader import VideoMetadata

client = TestClient(app)

_MOCK_METADATA = VideoMetadata(
    duration=120,
    title="Test Video",
    video_id="dQw4w9WgXcQ",
    height=1080,
    filesize_approx=50 * 1024 * 1024,
)

_TEST_USER_ID = "test_user_id1"
_TEST_USERNAME = "apitestuser"
_TEST_PASSWORD = "Test1234!"


def _reset_rate_limiter():
    stack = app.middleware_stack
    while stack is not None:
        if isinstance(stack, RateLimitMiddleware):
            stack.reset()
            return
        stack = getattr(stack, "app", None)


@pytest.fixture(autouse=True)
def _clear_jobs():
    """각 테스트 전후로 작업 저장소를 초기화한다."""
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
    """테스트용 인증 헤더를 반환한다."""
    resp = client.post(
        "/auth/login",
        data={"username": _TEST_USERNAME, "password": _TEST_PASSWORD},
    )
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _insert_job(job_id: str, **fields) -> None:
    """테스트용 Job을 DB에 직접 삽입한다."""
    defaults = {
        "status": JobStatus.pending,
        "url": "https://youtu.be/dQw4w9WgXcQ",
        "error": None,
        "result": None,
    }
    defaults.update(fields)
    _job_store.create(
        job_id,
        defaults["status"],
        defaults["url"],
        user_id=_TEST_USER_ID,
    )
    update_fields = {}
    if defaults["error"] is not None:
        update_fields["error"] = defaults["error"]
    if defaults["result"] is not None:
        update_fields["result"] = defaults["result"]
    if defaults.get("ply_path") is not None:
        update_fields["ply_path"] = defaults["ply_path"]
    # Update status if not pending (create always sets the given status, so we
    # only need to update if extra fields exist)
    if defaults["status"] != JobStatus.pending:
        update_fields["status"] = defaults["status"]
    if update_fields:
        _job_store.update(job_id, **update_fields)


class TestCreateJob:
    """POST /api/jobs 테스트."""

    def test_invalid_url_returns_400(self):
        """유효하지 않은 URL은 400을 반환한다."""
        headers = _get_auth_headers()
        resp = client.post("/api/jobs", json={"url": "not-a-url"}, headers=headers)
        assert resp.status_code == 400
        assert "유효하지 않은" in resp.json()["detail"]

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_valid_url_creates_job(self, mock_meta, mock_run):
        """유효한 URL로 작업을 생성한다."""
        headers = _get_auth_headers()
        resp = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers=headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["url"] == ("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert _job_store.get(data["id"]) is not None

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_custom_params(self, mock_meta, mock_run):
        """커스텀 파라미터가 전달된다."""
        headers = _get_auth_headers()
        resp = client.post(
            "/api/jobs",
            json={
                "url": "https://youtu.be/dQw4w9WgXcQ",
                "max_height": 720,
                "frame_interval": 2.0,
            },
            headers=headers,
        )
        assert resp.status_code == 201

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        job_id = call_args[0][0]
        params = call_args[0][1]
        assert _job_store.get(job_id) is not None
        assert params.url == "https://youtu.be/dQw4w9WgXcQ"
        assert params.max_height == 720
        assert params.frame_interval == 2.0
        assert params.blur_threshold == 100.0
        assert params.camera_model == "SIMPLE_RADIAL"

    def test_xss_url_sanitized(self):
        """XSS가 포함된 URL은 sanitize된다."""
        headers = _get_auth_headers()
        resp = client.post(
            "/api/jobs",
            json={"url": "<script>alert('xss')</script>"},
            headers=headers,
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "<script>" not in detail
        assert "'" not in detail


class TestJobConcurrencyLimit:
    """사용자별 동시 실행 제한 테스트."""

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_within_limit_succeeds(self, mock_meta, mock_run):
        """제한 이내의 Job 생성은 성공한다."""
        headers = _get_auth_headers()
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        # 기본 제한은 2개
        resp1 = client.post("/api/jobs", json={"url": url}, headers=headers)
        assert resp1.status_code == 201
        resp2 = client.post("/api/jobs", json={"url": url}, headers=headers)
        assert resp2.status_code == 201

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_exceeding_limit_returns_429(self, mock_meta, mock_run):
        """제한 초과 시 429를 반환한다."""
        headers = _get_auth_headers()
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        # 2개 생성 (pending 상태)
        client.post("/api/jobs", json={"url": url}, headers=headers)
        client.post("/api/jobs", json={"url": url}, headers=headers)
        # 3번째는 거부
        resp = client.post("/api/jobs", json={"url": url}, headers=headers)
        assert resp.status_code == 429
        assert "동시 실행 제한 초과" in resp.json()["detail"]

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_completed_jobs_not_counted(self, mock_meta, mock_run):
        """완료된 Job은 제한에 포함되지 않는다."""
        headers = _get_auth_headers()
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        # 2개 생성 후 1개 완료 (force_reprocess로 캐시 우회)
        resp1 = client.post(
            "/api/jobs", json={"url": url, "force_reprocess": True}, headers=headers
        )
        client.post(
            "/api/jobs", json={"url": url, "force_reprocess": True}, headers=headers
        )
        job_id = resp1.json()["id"]
        _job_store.update(job_id, status=JobStatus.completed)
        # 완료된 건 제외하므로 새 Job 생성 가능
        resp = client.post(
            "/api/jobs", json={"url": url, "force_reprocess": True}, headers=headers
        )
        assert resp.status_code == 201

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_failed_jobs_not_counted(self, mock_meta, mock_run):
        """실패한 Job은 제한에 포함되지 않는다."""
        headers = _get_auth_headers()
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        # 2개 생성 후 1개 실패
        resp1 = client.post("/api/jobs", json={"url": url}, headers=headers)
        client.post("/api/jobs", json={"url": url}, headers=headers)
        job_id = resp1.json()["id"]
        _job_store.update(job_id, status=JobStatus.failed, error="test error")
        # 실패한 건 제외하므로 새 Job 생성 가능
        resp = client.post("/api/jobs", json={"url": url}, headers=headers)
        assert resp.status_code == 201

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_processing_jobs_counted(self, mock_meta, mock_run):
        """처리 중인 Job도 제한에 포함된다."""
        headers = _get_auth_headers()
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        # 1개 생성 후 processing으로 전환
        resp1 = client.post("/api/jobs", json={"url": url}, headers=headers)
        _job_store.update(resp1.json()["id"], status=JobStatus.processing)
        # 1개 더 pending으로 생성
        client.post("/api/jobs", json={"url": url}, headers=headers)
        # 3번째 (pending 1 + processing 1 = 2) 거부
        resp = client.post("/api/jobs", json={"url": url}, headers=headers)
        assert resp.status_code == 429


class TestDuplicateUrlPrevention:
    """동일 URL 중복 처리 방지 테스트."""

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_duplicate_url_returns_existing_job(self, mock_meta, mock_enqueue):
        """동일 URL의 완료된 Job이 있으면 기존 결과를 반환한다."""
        headers = _get_auth_headers()
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        _insert_job("aabbccddeef0", status=JobStatus.completed, url=url)
        resp = client.post("/api/jobs", json={"url": url}, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == "aabbccddeef0"
        assert resp.json()["status"] == "completed"
        mock_enqueue.assert_not_called()

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_force_reprocess_creates_new_job(self, mock_meta, mock_enqueue):
        """force_reprocess=true이면 기존 결과가 있어도 새 Job을 생성한다."""
        headers = _get_auth_headers()
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        _insert_job("aabbccddeef0", status=JobStatus.completed, url=url)
        resp = client.post(
            "/api/jobs",
            json={"url": url, "force_reprocess": True},
            headers=headers,
        )
        assert resp.status_code == 201
        assert resp.json()["id"] != "aabbccddeef0"
        assert resp.json()["status"] == "pending"
        mock_enqueue.assert_called_once()

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_no_completed_job_creates_new(self, mock_meta, mock_enqueue):
        """완료된 Job이 없으면 새 Job을 생성한다."""
        headers = _get_auth_headers()
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        _insert_job("aabbccddeef0", status=JobStatus.failed, url=url, error="err")
        resp = client.post("/api/jobs", json={"url": url}, headers=headers)
        assert resp.status_code == 201
        assert resp.json()["id"] != "aabbccddeef0"
        mock_enqueue.assert_called_once()

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_other_user_completed_job_not_returned(self, mock_meta, mock_enqueue):
        """다른 유저의 완료된 Job은 반환하지 않는다."""
        headers = _get_auth_headers()
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        # 다른 유저의 Job을 직접 삽입
        _job_store.create("aabbccddeef0", "completed", url, user_id="other_user_id")
        resp = client.post("/api/jobs", json={"url": url}, headers=headers)
        assert resp.status_code == 201
        assert resp.json()["id"] != "aabbccddeef0"
        mock_enqueue.assert_called_once()


class TestGetJob:
    """GET /api/jobs/{id} 테스트."""

    def test_not_found(self):
        """존재하지 않는 작업은 404를 반환한다."""
        headers = _get_auth_headers()
        resp = client.get("/api/jobs/nonexistent", headers=headers)
        assert resp.status_code == 404

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_get_pending_job(self, mock_meta, mock_run):
        """생성된 작업의 상태를 조회한다."""
        headers = _get_auth_headers()
        create_resp = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers=headers,
        )
        job_id = create_resp.json()["id"]

        resp = client.get(f"/api/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    def test_get_completed_job(self):
        """완료된 작업 조회."""
        headers = _get_auth_headers()
        _insert_job(
            "aabbccddeeff",
            status=JobStatus.completed,
            result={"num_points3d": 100},
        )
        resp = client.get("/api/jobs/aabbccddeeff", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"]["num_points3d"] == 100

    def test_get_failed_job(self):
        """실패한 작업 조회."""
        headers = _get_auth_headers()
        _insert_job(
            "aabbccddeef1",
            status=JobStatus.failed,
            error="COLMAP 실패",
        )
        resp = client.get("/api/jobs/aabbccddeef1", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["error"] == "COLMAP 실패"


class TestListJobs:
    """GET /api/jobs 테스트."""

    def test_empty_list(self):
        """Job이 없으면 빈 목록을 반환한다."""
        headers = _get_auth_headers()
        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1
        assert data["per_page"] == 20
        assert data["total_pages"] == 1

    def test_list_all_jobs(self):
        """모든 Job 목록을 반환한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddee01", status=JobStatus.completed)
        _insert_job("aabbccddee02", status=JobStatus.failed, error="err")
        _insert_job("aabbccddee03", status=JobStatus.processing)
        resp = client.get("/api/jobs", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

    def test_filter_by_status(self):
        """상태별 필터링이 동작한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddee04", status=JobStatus.completed)
        _insert_job("aabbccddee05", status=JobStatus.failed, error="err")
        resp = client.get("/api/jobs?status=completed", headers=headers)
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["status"] == "completed"

    def test_pagination(self):
        """페이지네이션이 동작한다."""
        headers = _get_auth_headers()
        for i in range(5):
            _insert_job(f"aabbccddee{i:02d}", status=JobStatus.completed)
        resp = client.get("/api/jobs?per_page=2&page=1", headers=headers)
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["page"] == 1
        assert data["per_page"] == 2
        assert data["total_pages"] == 3

        resp2 = client.get("/api/jobs?per_page=2&page=3", headers=headers)
        data2 = resp2.json()
        assert len(data2["items"]) == 1

    def test_sort_by_status_asc(self):
        """상태 기준 오름차순 정렬이 동작한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddee06", status=JobStatus.processing)
        _insert_job("aabbccddee07", status=JobStatus.completed)
        resp = client.get("/api/jobs?sort_by=status&order=asc", headers=headers)
        data = resp.json()
        assert data["items"][0]["status"] == "completed"
        assert data["items"][1]["status"] == "processing"

    def test_invalid_sort_by(self):
        """잘못된 sort_by 값은 422를 반환한다."""
        headers = _get_auth_headers()
        resp = client.get("/api/jobs?sort_by=invalid", headers=headers)
        assert resp.status_code == 422

    def test_invalid_order(self):
        """잘못된 order 값은 422를 반환한다."""
        headers = _get_auth_headers()
        resp = client.get("/api/jobs?order=invalid", headers=headers)
        assert resp.status_code == 422

    def test_invalid_status(self):
        """잘못된 상태 값은 422를 반환한다."""
        headers = _get_auth_headers()
        resp = client.get("/api/jobs?status=invalid", headers=headers)
        assert resp.status_code == 422


class TestDeleteJob:
    """DELETE /api/jobs/{id} 테스트."""

    def test_not_found(self):
        """존재하지 않는 작업은 404를 반환한다."""
        headers = _get_auth_headers()
        resp = client.delete("/api/jobs/nonexistent", headers=headers)
        assert resp.status_code == 404

    def test_processing_returns_409(self):
        """처리 중인 작업은 409를 반환한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeef9", status=JobStatus.processing)
        resp = client.delete("/api/jobs/aabbccddeef9", headers=headers)
        assert resp.status_code == 409
        assert "처리 중" in resp.json()["detail"]

    def test_delete_completed_job(self):
        """완료된 작업을 삭제한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeed1", status=JobStatus.completed)
        resp = client.delete("/api/jobs/aabbccddeed1", headers=headers)
        assert resp.status_code == 204
        assert _job_store.get("aabbccddeed1") is None

    def test_delete_failed_job(self):
        """실패한 작업을 삭제한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeed2", status=JobStatus.failed, error="err")
        resp = client.delete("/api/jobs/aabbccddeed2", headers=headers)
        assert resp.status_code == 204
        assert _job_store.get("aabbccddeed2") is None

    def test_delete_pending_job(self):
        """대기 중인 작업을 삭제한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeed3", status=JobStatus.pending)
        resp = client.delete("/api/jobs/aabbccddeed3", headers=headers)
        assert resp.status_code == 204
        assert _job_store.get("aabbccddeed3") is None

    @patch("src.api.dependencies.get_output_base_dir")
    def test_delete_cleans_disk(self, mock_base_dir, tmp_path):
        """삭제 시 디스크 파일도 정리한다."""
        headers = _get_auth_headers()
        mock_base_dir.return_value = tmp_path
        job_dir = tmp_path / "aabbccddeed4"
        job_dir.mkdir(parents=True)
        (job_dir / "test.txt").write_text("data")

        _insert_job("aabbccddeed4", status=JobStatus.completed)
        resp = client.delete("/api/jobs/aabbccddeed4", headers=headers)
        assert resp.status_code == 204
        assert not job_dir.exists()


class TestCancelJob:
    """POST /api/jobs/{id}/cancel 테스트."""

    def test_not_found(self):
        """존재하지 않는 작업은 404를 반환한다."""
        headers = _get_auth_headers()
        resp = client.post("/api/jobs/nonexistent/cancel", headers=headers)
        assert resp.status_code == 404

    @patch("src.api.routers.jobs._get_redis_connection")
    def test_cancel_pending_job(self, mock_redis):
        """대기 중인 작업을 취소한다."""
        headers = _get_auth_headers()
<<<<<<< Updated upstream
        _mock_conn = mock_redis.return_value  # noqa: F841
=======
        _ = mock_redis.return_value
>>>>>>> Stashed changes
        _insert_job("aabbccddeca1", status=JobStatus.pending)
        resp = client.post("/api/jobs/aabbccddeca1/cancel", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert _job_store.get("aabbccddeca1")["status"] == "cancelled"

    @patch("src.api.routers.jobs._get_redis_connection")
    def test_cancel_processing_job(self, mock_redis):
        """처리 중인 작업을 취소한다."""
        headers = _get_auth_headers()
<<<<<<< Updated upstream
        _mock_conn = mock_redis.return_value  # noqa: F841
=======
        _ = mock_redis.return_value
>>>>>>> Stashed changes
        _insert_job("aabbccddeca2", status=JobStatus.processing)
        resp = client.post("/api/jobs/aabbccddeca2/cancel", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    @patch("src.api.routers.jobs._get_redis_connection")
    def test_cancel_retrying_job(self, mock_redis):
        """재시도 중인 작업을 취소한다."""
        headers = _get_auth_headers()
<<<<<<< Updated upstream
        _mock_conn = mock_redis.return_value  # noqa: F841
=======
        _ = mock_redis.return_value
>>>>>>> Stashed changes
        _insert_job("aabbccddeca3", status=JobStatus.retrying)
        resp = client.post("/api/jobs/aabbccddeca3/cancel", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    def test_cancel_completed_returns_409(self):
        """완료된 작업은 취소할 수 없다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeca4", status=JobStatus.completed)
        resp = client.post("/api/jobs/aabbccddeca4/cancel", headers=headers)
        assert resp.status_code == 409
        assert "취소할 수 없는 상태" in resp.json()["detail"]

    def test_cancel_failed_returns_409(self):
        """실패한 작업은 취소할 수 없다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeca5", status=JobStatus.failed, error="err")
        resp = client.post("/api/jobs/aabbccddeca5/cancel", headers=headers)
        assert resp.status_code == 409

    @patch("src.api.routers.jobs._get_redis_connection")
    def test_cancel_already_cancelled_returns_409(self, mock_redis):
        """이미 취소된 작업은 다시 취소할 수 없다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeca6", status=JobStatus.cancelled)
        resp = client.post("/api/jobs/aabbccddeca6/cancel", headers=headers)
        assert resp.status_code == 409

    def test_stream_cancelled_job(self):
        """취소된 작업은 최종 이벤트를 전송한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeca7", status=JobStatus.cancelled)
        resp = client.get("/api/jobs/aabbccddeca7/stream", headers=headers)
        assert resp.status_code == 200
        events = _parse_sse_events(resp)
        assert len(events) == 1
        assert events[0]["status"] == "cancelled"

    def test_delete_cancelled_job(self):
        """취소된 작업을 삭제할 수 있다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeca8", status=JobStatus.cancelled)
        resp = client.delete("/api/jobs/aabbccddeca8", headers=headers)
        assert resp.status_code == 204
        assert _job_store.get("aabbccddeca8") is None

    @patch("src.api.routers.jobs._get_redis_connection")
    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata", return_value=_MOCK_METADATA)
    def test_cancelled_jobs_not_counted_in_limit(
        self, mock_meta, mock_enqueue, mock_redis
    ):
        """취소된 Job은 동시 실행 제한에 포함되지 않는다."""
        headers = _get_auth_headers()
<<<<<<< Updated upstream
        _mock_conn = mock_redis.return_value  # noqa: F841
=======
        _ = mock_redis.return_value
>>>>>>> Stashed changes
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        # 2개 생성
        resp1 = client.post("/api/jobs", json={"url": url}, headers=headers)
        client.post("/api/jobs", json={"url": url}, headers=headers)
        # 1개 취소
        client.post(f"/api/jobs/{resp1.json()['id']}/cancel", headers=headers)
        # 취소된 건 제외하므로 새 Job 생성 가능
        resp = client.post("/api/jobs", json={"url": url}, headers=headers)
        assert resp.status_code == 201


class TestGetJobResult:
    """GET /api/jobs/{id}/result 테스트."""

    def test_not_found(self):
        """존재하지 않는 작업은 404를 반환한다."""
        headers = _get_auth_headers()
        resp = client.get("/api/jobs/nonexistent/result", headers=headers)
        assert resp.status_code == 404

    def test_not_completed(self):
        """완료되지 않은 작업은 400을 반환한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeef2", status=JobStatus.processing)
        resp = client.get("/api/jobs/aabbccddeef2/result", headers=headers)
        assert resp.status_code == 400
        assert "완료되지 않았습니다" in resp.json()["detail"]

    def test_ply_not_found(self):
        """PLY 파일이 없으면 404를 반환한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeef3", status=JobStatus.completed)
        resp = client.get("/api/jobs/aabbccddeef3/result", headers=headers)
        assert resp.status_code == 404

    @patch("src.api.dependencies.get_output_base_dir")
    def test_download_ply(self, mock_base_dir, tmp_path):
        """PLY 파일을 다운로드한다."""
        headers = _get_auth_headers()
        mock_base_dir.return_value = tmp_path
        ply_file = tmp_path / "points.ply"
        ply_file.write_text("ply content")

        _insert_job(
            "aabbccddeef4",
            status=JobStatus.completed,
            ply_path=str(ply_file),
        )
        resp = client.get("/api/jobs/aabbccddeef4/result", headers=headers)
        assert resp.status_code == 200
        assert resp.content == b"ply content"


class TestGetSplatFile:
    """GET /api/jobs/{id}/splat 테스트."""

    def test_not_found(self):
        """존재하지 않는 작업은 404를 반환한다."""
        headers = _get_auth_headers()
        resp = client.get("/api/jobs/nonexistent/splat", headers=headers)
        assert resp.status_code == 404

    def test_not_completed(self):
        """완료되지 않은 작업은 400을 반환한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddees1", status=JobStatus.processing)
        resp = client.get("/api/jobs/aabbccddees1/splat", headers=headers)
        assert resp.status_code == 400

    def test_no_splat_path(self):
        """gs_splat_path가 없으면 404를 반환한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddees2", status=JobStatus.completed)
        resp = client.get("/api/jobs/aabbccddees2/splat", headers=headers)
        assert resp.status_code == 404

    @patch("src.api.dependencies.get_output_base_dir")
    def test_serve_splat_file(self, mock_base_dir, tmp_path):
        """GS splat 파일을 서빙한다."""
        headers = _get_auth_headers()
        mock_base_dir.return_value = tmp_path
        splat_file = tmp_path / "point_cloud.ply"
        splat_file.write_bytes(b"splat binary data")

        _insert_job("aabbccddees3", status=JobStatus.completed)
        _job_store.update("aabbccddees3", gs_splat_path=str(splat_file))
        resp = client.get("/api/jobs/aabbccddees3/splat", headers=headers)
        assert resp.status_code == 200
        assert resp.content == b"splat binary data"

    def test_response_includes_gs_splat_url(self):
        """gs_splat_path가 있으면 응답에 gs_splat_url이 포함된다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddees4", status=JobStatus.completed)
        _job_store.update("aabbccddees4", gs_splat_path="/some/path.ply")
        resp = client.get("/api/jobs/aabbccddees4", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["gs_splat_url"] == "/api/jobs/aabbccddees4/splat"

    def test_response_no_gs_splat_url(self):
        """gs_splat_path가 없으면 gs_splat_url은 null이다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddees5", status=JobStatus.completed)
        resp = client.get("/api/jobs/aabbccddees5", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["gs_splat_url"] is None


def _parse_sse_events(response) -> list[dict]:
    """SSE 응답에서 data 이벤트를 파싱한다."""
    events = []
    for line in response.text.strip().split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


class TestHealth:
    """GET /health, /health/ready 테스트."""

    def test_health_ok(self):
        """기본 헬스체크는 200을 반환한다."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_health_ready_db_ok(self):
        """/health/ready는 DB가 정상이면 checks에 database=ok를 포함한다."""
        resp = client.get("/health/ready")
        data = resp.json()
        # colmap/redis가 없을 수 있으므로 DB 체크만 확인
        if resp.status_code == 200:
            assert data["checks"]["database"] == "ok"
        else:
            # 503일 경우 detail에서 database 확인
            detail = data["detail"]
            assert detail["database"] == "ok" or "error" in detail["database"]

    @patch("src.api.routers.jobs._get_redis_connection")
    @patch("src.api.dependencies._job_store")
    def test_health_ready_db_failure(self, mock_store, mock_redis):
        """DB 연결 실패 시 503을 반환한다."""
        mock_store.ping.side_effect = RuntimeError("DB 연결 실패")
        resp = client.get("/health/ready")
        assert resp.status_code == 503


class TestGetPotreeFile:
    """GET /api/jobs/{id}/potree/{file_path} 테스트."""

    def test_not_found(self):
        """존재하지 않는 작업은 404를 반환한다."""
        headers = _get_auth_headers()
        resp = client.get("/api/jobs/nonexistent/potree/metadata.json", headers=headers)
        assert resp.status_code == 404

    def test_not_completed(self):
        """완료되지 않은 작업은 400을 반환한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeea1", status=JobStatus.processing)
        url = "/api/jobs/aabbccddeea1/potree/metadata.json"
        resp = client.get(url, headers=headers)
        assert resp.status_code == 400

    def test_no_potree_dir(self):
        """potree_dir이 없으면 404를 반환한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeea2", status=JobStatus.completed)
        url = "/api/jobs/aabbccddeea2/potree/metadata.json"
        resp = client.get(url, headers=headers)
        assert resp.status_code == 404

    @patch("src.api.dependencies.get_output_base_dir")
    def test_serve_potree_file(self, mock_base_dir, tmp_path):
        """Potree 파일을 서빙한다."""
        headers = _get_auth_headers()
        mock_base_dir.return_value = tmp_path
        potree_dir = tmp_path / "potree"
        potree_dir.mkdir()
        meta = potree_dir / "metadata.json"
        meta.write_text('{"version": "2.0"}')

        _insert_job("aabbccddeea3", status=JobStatus.completed)
        _job_store.update("aabbccddeea3", potree_dir=str(potree_dir))
        url = "/api/jobs/aabbccddeea3/potree/metadata.json"
        resp = client.get(url, headers=headers)
        assert resp.status_code == 200
        assert resp.json() == {"version": "2.0"}

    @patch("src.api.dependencies.get_output_base_dir")
    def test_path_traversal_blocked(self, mock_base_dir, tmp_path):
        """경로 순회 공격이 차단된다."""
        headers = _get_auth_headers()
        mock_base_dir.return_value = tmp_path
        potree_dir = tmp_path / "potree"
        potree_dir.mkdir()

        _insert_job("aabbccddeea4", status=JobStatus.completed)
        _job_store.update("aabbccddeea4", potree_dir=str(potree_dir))
        resp = client.get(
            "/api/jobs/aabbccddeea4/potree/../../etc/passwd",
            headers=headers,
        )
        assert resp.status_code in (400, 404)


class TestStreamJob:
    """GET /api/jobs/{id}/stream 테스트."""

    def test_stream_not_found(self):
        """존재하지 않는 작업은 404를 반환한다."""
        headers = _get_auth_headers()
        resp = client.get("/api/jobs/nonexistent/stream", headers=headers)
        assert resp.status_code == 404

    def test_stream_completed_job(self):
        """완료된 작업은 최종 이벤트 1개만 전송한다."""
        headers = _get_auth_headers()
        _insert_job(
            "aabbccddeef5",
            status=JobStatus.completed,
            result={"num_points3d": 42},
        )
        resp = client.get("/api/jobs/aabbccddeef5/stream", headers=headers)
        assert resp.status_code == 200
        events = _parse_sse_events(resp)
        assert len(events) == 1
        assert events[0]["status"] == "completed"
        assert events[0]["result"]["num_points3d"] == 42

    def test_stream_failed_job(self):
        """실패한 작업은 에러 이벤트를 전송한다."""
        headers = _get_auth_headers()
        _insert_job(
            "aabbccddeef6",
            status=JobStatus.failed,
            error="COLMAP 실패",
        )
        resp = client.get("/api/jobs/aabbccddeef6/stream", headers=headers)
        assert resp.status_code == 200
        events = _parse_sse_events(resp)
        assert len(events) == 1
        assert events[0]["status"] == "failed"
        assert events[0]["error"] == "COLMAP 실패"

    def test_stream_no_duplicate_on_completion(self):
        """완료 시 progress 이벤트와 completed 이벤트가 중복 전송되지 않는다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeef7", status=JobStatus.completed)
        _job_store.update(
            "aabbccddeef7",
            progress={"stage": "reconstruction", "percent": 100, "message": "완료"},
        )
        resp = client.get("/api/jobs/aabbccddeef7/stream", headers=headers)
        events = _parse_sse_events(resp)
        assert len(events) == 1
        assert events[0]["status"] == "completed"

    @patch("src.api.routers.jobs._SSE_TIMEOUT_SECONDS", 0)
    def test_stream_timeout(self):
        """타임아웃 시 연결이 종료된다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeef8", status=JobStatus.processing)
        resp = client.get("/api/jobs/aabbccddeef8/stream", headers=headers)
        events = _parse_sse_events(resp)
        assert any(e.get("status") == "timeout" for e in events)


class TestListJobFiles:
    """GET /api/jobs/{id}/files 테스트."""

    def test_not_found(self):
        """존재하지 않는 작업은 404를 반환한다."""
        headers = _get_auth_headers()
        resp = client.get("/api/jobs/nonexistent/files", headers=headers)
        assert resp.status_code == 404

    def test_not_completed(self):
        """완료되지 않은 작업은 400을 반환한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeeb1", status=JobStatus.processing)
        resp = client.get("/api/jobs/aabbccddeeb1/files", headers=headers)
        assert resp.status_code == 400

    @patch("src.api.dependencies.get_output_base_dir")
    def test_list_files(self, mock_base_dir, tmp_path):
        """결과 파일 목록을 반환한다."""
        headers = _get_auth_headers()
        mock_base_dir.return_value = tmp_path
        job_dir = tmp_path / "aabbccddeeb2"
        recon_dir = job_dir / "reconstruction"
        recon_dir.mkdir(parents=True)
        (recon_dir / "points.ply").write_text("ply data")
        (recon_dir / "cameras.txt").write_text("camera data")

        _insert_job("aabbccddeeb2", status=JobStatus.completed)
        resp = client.get("/api/jobs/aabbccddeeb2/files", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "aabbccddeeb2"
        names = [f["name"] for f in data["files"]]
        assert "points.ply" in names
        assert "cameras.txt" in names

    @patch("src.api.dependencies.get_output_base_dir")
    def test_no_reconstruction_dir(self, mock_base_dir, tmp_path):
        """reconstruction 디렉토리가 없으면 빈 목록을 반환한다."""
        headers = _get_auth_headers()
        mock_base_dir.return_value = tmp_path
        job_dir = tmp_path / "aabbccddeeb3"
        job_dir.mkdir(parents=True)

        _insert_job("aabbccddeeb3", status=JobStatus.completed)
        resp = client.get("/api/jobs/aabbccddeeb3/files", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["files"] == []


class TestDownloadJobFile:
    """GET /api/jobs/{id}/download/{file_path} 테스트."""

    def test_not_found(self):
        """존재하지 않는 작업은 404를 반환한다."""
        headers = _get_auth_headers()
        resp = client.get("/api/jobs/nonexistent/download/points.ply", headers=headers)
        assert resp.status_code == 404

    def test_not_completed(self):
        """완료되지 않은 작업은 400을 반환한다."""
        headers = _get_auth_headers()
        _insert_job("aabbccddeec1", status=JobStatus.processing)
        resp = client.get(
            "/api/jobs/aabbccddeec1/download/points.ply",
            headers=headers,
        )
        assert resp.status_code == 400

    @patch("src.api.dependencies.get_output_base_dir")
    def test_download_file(self, mock_base_dir, tmp_path):
        """결과 파일을 다운로드한다."""
        headers = _get_auth_headers()
        mock_base_dir.return_value = tmp_path
        job_dir = tmp_path / "aabbccddeec2"
        recon_dir = job_dir / "reconstruction"
        recon_dir.mkdir(parents=True)
        (recon_dir / "points.ply").write_bytes(b"ply binary data")

        _insert_job("aabbccddeec2", status=JobStatus.completed)
        resp = client.get(
            "/api/jobs/aabbccddeec2/download/points.ply",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.content == b"ply binary data"
        assert "attachment" in resp.headers.get("content-disposition", "")

    @patch("src.api.dependencies.get_output_base_dir")
    def test_file_not_exists(self, mock_base_dir, tmp_path):
        """존재하지 않는 파일은 404를 반환한다."""
        headers = _get_auth_headers()
        mock_base_dir.return_value = tmp_path
        job_dir = tmp_path / "aabbccddeec3"
        recon_dir = job_dir / "reconstruction"
        recon_dir.mkdir(parents=True)

        _insert_job("aabbccddeec3", status=JobStatus.completed)
        resp = client.get(
            "/api/jobs/aabbccddeec3/download/nonexistent.ply",
            headers=headers,
        )
        assert resp.status_code == 404

    @patch("src.api.dependencies.get_output_base_dir")
    def test_path_traversal_blocked(self, mock_base_dir, tmp_path):
        """경로 순회 공격이 차단된다."""
        headers = _get_auth_headers()
        mock_base_dir.return_value = tmp_path
        job_dir = tmp_path / "aabbccddeec4"
        recon_dir = job_dir / "reconstruction"
        recon_dir.mkdir(parents=True)

        _insert_job("aabbccddeec4", status=JobStatus.completed)
        resp = client.get(
            "/api/jobs/aabbccddeec4/download/../../etc/passwd",
            headers=headers,
        )
        assert resp.status_code in (400, 404)

    @patch("src.api.dependencies.get_output_base_dir")
    def test_download_nested_file(self, mock_base_dir, tmp_path):
        """하위 디렉토리의 파일도 다운로드할 수 있다."""
        headers = _get_auth_headers()
        mock_base_dir.return_value = tmp_path
        job_dir = tmp_path / "aabbccddeec5"
        recon_dir = job_dir / "reconstruction"
        sub_dir = recon_dir / "sparse"
        sub_dir.mkdir(parents=True)
        (sub_dir / "cameras.bin").write_bytes(b"camera binary")

        _insert_job("aabbccddeec5", status=JobStatus.completed)
        resp = client.get(
            "/api/jobs/aabbccddeec5/download/sparse/cameras.bin",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.content == b"camera binary"


class TestOpenAPIDocs:
    """OpenAPI 문서 테스트."""

    def test_openapi_schema(self):
        """OpenAPI 스키마가 올바르게 생성된다."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert schema["info"]["title"] == "EXTube API"
        assert schema["info"]["version"] == "0.5.0"
        assert "/api/jobs" in schema["paths"]
        assert "/auth/login" in schema["paths"]

    def test_docs_available_in_dev(self):
        """/docs가 개발 환경에서 접근 가능하다."""
        resp = client.get("/docs")
        assert resp.status_code == 200

    def test_redoc_available_in_dev(self):
        """/redoc이 개발 환경에서 접근 가능하다."""
        resp = client.get("/redoc")
        assert resp.status_code == 200

    def test_endpoints_have_tags(self):
        """주요 엔드포인트에 태그가 설정되어 있다."""
        resp = client.get("/openapi.json")
        schema = resp.json()
        jobs_post = schema["paths"]["/api/jobs"]["post"]
        assert "jobs" in jobs_post.get("tags", [])

    def test_endpoints_have_summary(self):
        """주요 엔드포인트에 summary가 설정되어 있다."""
        resp = client.get("/openapi.json")
        schema = resp.json()
        jobs_post = schema["paths"]["/api/jobs"]["post"]
        assert jobs_post.get("summary") is not None


class TestMetrics:
    """Prometheus /metrics 엔드포인트 테스트."""

    def test_metrics_endpoint_returns_prometheus_format(self):
        """/metrics가 Prometheus exposition format을 반환한다."""
        resp = client.get("/metrics")
        assert resp.status_code == 200
        body = resp.text
        assert "http_request" in body or "http_requests" in body
        assert "extube_active_jobs" in body
        assert "extube_queue_length" in body

    def test_metrics_active_jobs_reflects_db(self):
        """활성 Job 수가 메트릭에 반영된다."""
        _insert_job("aabbccddee01", status=JobStatus.pending)
        _insert_job("aabbccddee02", status=JobStatus.processing)
        resp = client.get("/metrics")
        body = resp.text
        # extube_active_jobs should be 2.0
        assert "extube_active_jobs 2.0" in body


class TestVideoValidation:
    """영상 길이/크기 제한 테스트."""

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata")
    def test_duration_exceeds_limit(self, mock_meta, mock_enqueue):
        """영상 길이 초과 시 422를 반환한다."""
        mock_meta.return_value = VideoMetadata(
            duration=700,
            title="Long Video",
            video_id="abc",
            height=1080,
            filesize_approx=100 * 1024 * 1024,
        )
        headers = _get_auth_headers()
        resp = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "영상 길이" in resp.json()["detail"]
        mock_enqueue.assert_not_called()

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata")
    def test_filesize_exceeds_limit(self, mock_meta, mock_enqueue):
        """예상 파일 크기 초과 시 422를 반환한다."""
        mock_meta.return_value = VideoMetadata(
            duration=60,
            title="Big Video",
            video_id="abc",
            height=1080,
            filesize_approx=600 * 1024 * 1024,
        )
        headers = _get_auth_headers()
        resp = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "파일 크기" in resp.json()["detail"]
        mock_enqueue.assert_not_called()

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata")
    def test_metadata_fetch_failure(self, mock_meta, mock_enqueue):
        """메타데이터 조회 실패 시 422를 반환한다."""
        mock_meta.side_effect = RuntimeError("네트워크 오류")
        headers = _get_auth_headers()
        resp = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers=headers,
        )
        assert resp.status_code == 503
        assert "영상 정보를 가져올 수 없습니다" in resp.json()["detail"]

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata")
    def test_duration_none_rejected(self, mock_meta, mock_enqueue):
        """duration=None(라이브 스트림 등)은 422를 반환한다."""
        mock_meta.return_value = VideoMetadata(
            duration=None,
            title="Live Stream",
            video_id="abc",
            height=1080,
            filesize_approx=None,
        )
        headers = _get_auth_headers()
        resp = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers=headers,
        )
        assert resp.status_code == 422
        assert "영상 길이를 확인할 수 없습니다" in resp.json()["detail"]
        mock_enqueue.assert_not_called()

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata")
    def test_within_limits_succeeds(self, mock_meta, mock_enqueue):
        """제한 이내 영상은 정상 생성된다."""
        mock_meta.return_value = VideoMetadata(
            duration=300,
            title="OK Video",
            video_id="abc",
            height=720,
            filesize_approx=100 * 1024 * 1024,
        )
        headers = _get_auth_headers()
        resp = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers=headers,
        )
        assert resp.status_code == 201

    @patch("src.api.routers.jobs._enqueue_job")
    @patch("src.api.routers.jobs.fetch_video_metadata")
    def test_no_filesize_info_passes(self, mock_meta, mock_enqueue):
        """파일 크기 정보가 없으면 크기 검증을 건너뛴다."""
        mock_meta.return_value = VideoMetadata(
            duration=60,
            title="No Size",
            video_id="abc",
            height=1080,
            filesize_approx=None,
        )
        headers = _get_auth_headers()
        resp = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers=headers,
        )
        assert resp.status_code == 201
