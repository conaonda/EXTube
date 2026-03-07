"""Job 재시도 메커니즘 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from src.api.main import _job_store, app
from src.api.rate_limit import RateLimitMiddleware
from src.api.routers.jobs import JobStatus
from src.api.tasks import is_retryable_error

client = TestClient(app)

_TEST_USER_ID = "test_user_id1"
_TEST_USERNAME = "retryuser"
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

    @patch("src.api.routers.jobs._enqueue_job")
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


class TestRetryParamsRestored:
    """재시도 시 원래 파라미터가 복원되는지 테스트."""

    @patch("src.api.routers.jobs._enqueue_job")
    def test_manual_retry_restores_params(self, mock_enqueue):
        """수동 재시도 시 저장된 파라미터가 복원된다."""
        _insert_job("aabbccddeeff", error="some error")
        stored_params = {
            "max_height": 720,
            "frame_interval": 2.0,
            "blur_threshold": 50.0,
            "camera_model": "PINHOLE",
            "dense": True,
            "max_image_size": 1024,
            "gaussian_splatting": True,
            "gs_max_iterations": 5000,
        }
        _job_store.update("aabbccddeeff", params=stored_params)
        headers = _get_auth_headers()

        resp = client.post("/api/jobs/aabbccddeeff/retry", headers=headers)
        assert resp.status_code == 200

        mock_enqueue.assert_called_once()
        _, kwargs = mock_enqueue.call_args
        body = kwargs.get("body") or mock_enqueue.call_args[0][1]
        assert body.max_height == 720
        assert body.frame_interval == 2.0
        assert body.blur_threshold == 50.0
        assert body.camera_model == "PINHOLE"
        assert body.dense is True
        assert body.max_image_size == 1024
        assert body.gaussian_splatting is True
        assert body.gs_max_iterations == 5000

    @patch("src.api.routers.jobs._enqueue_job")
    def test_manual_retry_without_params_uses_defaults(self, mock_enqueue):
        """파라미터가 저장되지 않은 Job 재시도 시 기본값을 사용한다."""
        _insert_job("aabbccddeeff", error="some error")
        headers = _get_auth_headers()

        resp = client.post("/api/jobs/aabbccddeeff/retry", headers=headers)
        assert resp.status_code == 200

        body = mock_enqueue.call_args[0][1]
        assert body.max_height == 1080
        assert body.frame_interval == 1.0

    def test_auto_retry_restores_params(self):
        """자동 재시도(_handle_pipeline_error) 시 저장된 파라미터가 전달된다."""
        from src.api.tasks import _handle_pipeline_error

        _insert_job("aabbccddeeff", status="processing")
        _job_store.update("aabbccddeeff", retry_count=0)
        stored_params = {
            "max_height": 720,
            "frame_interval": 2.0,
            "blur_threshold": 50.0,
            "camera_model": "PINHOLE",
            "dense": True,
            "max_image_size": 1024,
            "gaussian_splatting": False,
            "gs_max_iterations": None,
        }
        _job_store.update("aabbccddeeff", params=stored_params)

        mock_redis = MagicMock()
        mock_queue = MagicMock()

        with (
            patch("src.api.tasks._get_redis", return_value=mock_redis),
            patch("src.api.tasks.Queue", return_value=mock_queue),
        ):
            error = ConnectionError("Connection refused")
            _handle_pipeline_error("aabbccddeeff", error, _job_store, mock_redis)

        mock_queue.enqueue_in.assert_called_once()
        call_kwargs = mock_queue.enqueue_in.call_args[1]
        assert call_kwargs["max_height"] == 720
        assert call_kwargs["frame_interval"] == 2.0
        assert call_kwargs["camera_model"] == "PINHOLE"
        assert call_kwargs["dense"] is True


def _make_pipeline_mocks(tmp_path, job_id):
    """run_pipeline 테스트용 공통 mock 설정 헬퍼."""
    job_dir = tmp_path / "jobs" / job_id
    # tasks.py: frames_dir = job_dir / "extraction" / "frames"
    frames_dir = job_dir / "extraction" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    mock_job_store = MagicMock()
    mock_download = MagicMock()
    mock_download.return_value.title = "Test Video"
    mock_download.return_value.video_id = "test123"
    mock_download.return_value.resolution = "1080p"
    mock_download.return_value.video_path = tmp_path / "video.mp4"

    mock_extract = MagicMock()
    mock_extract.return_value.total_extracted = 3
    mock_extract.return_value.total_filtered = 0

    mock_redis = MagicMock()

    return job_dir, mock_job_store, mock_download, mock_extract, mock_redis


class TestColmapRetryWebSocketNotification:
    """COLMAP 재시도 시 WebSocket 알림 테스트."""

    def test_on_colmap_retry_updates_job_and_publishes_progress(self, tmp_path):
        """COLMAP 재시도 발생 시 job_store와 WebSocket 모두 업데이트된다."""
        from src.api.tasks import run_pipeline
        from src.reconstruction.reconstruction import ReconstructionResult

        def mock_reconstruct(*args, **kwargs):
            retry_cb = kwargs.get("retry_callback")
            if retry_cb:
                retry_cb("feature_extractor", 1, 3, "CUDA out of memory")
            return ReconstructionResult(
                workspace_dir=tmp_path / "ws",
                sparse_dir=tmp_path / "ws" / "sparse",
                num_images=3,
                num_registered=3,
                num_points3d=100,
                steps_completed=[
                    "feature_extraction",
                    "exhaustive_matching",
                    "sparse_reconstruction",
                ],
            )

        job_dir, mock_job_store, mock_download, mock_extract, mock_redis = (
            _make_pipeline_mocks(tmp_path, "colmapretry1")
        )

        with (
            patch("src.api.tasks._get_redis", return_value=mock_redis),
            patch("src.api.tasks.JobStore", return_value=mock_job_store),
            patch("src.api.tasks._validate_job_path", return_value=job_dir),
            patch("src.downloader.download_video", mock_download),
            patch("src.extractor.extract_and_filter", mock_extract),
            patch("src.reconstruction.reconstruct", side_effect=mock_reconstruct),
        ):
            run_pipeline("colmapretry1", "https://youtu.be/dQw4w9WgXcQ")

        # publish 호출 중 colmap_retry 단계가 포함된 것이 있는지 확인
        retry_calls = [
            c for c in mock_redis.publish.call_args_list
            if "colmap_retry" in str(c)
        ]
        assert len(retry_calls) >= 1, (
            "COLMAP 재시도 시 WebSocket 알림이 발행되어야 합니다"
        )

        # job_store.update가 colmap_retry progress로 호출되었는지 확인
        update_calls = [str(c) for c in mock_job_store.update.call_args_list]
        assert any("colmap_retry" in c for c in update_calls), (
            "COLMAP 재시도 시 job_store.update가 "
            "colmap_retry 진행 상태로 호출되어야 합니다"
        )

    def test_on_colmap_retry_progress_contains_required_fields(self, tmp_path):
        """COLMAP 재시도 WebSocket 메시지에 필수 필드가 포함된다."""
        import json as json_mod

        from src.api.tasks import run_pipeline
        from src.reconstruction.reconstruction import ReconstructionResult

        captured_retry_messages = []

        def mock_reconstruct(*args, **kwargs):
            retry_cb = kwargs.get("retry_callback")
            if retry_cb:
                retry_cb("mapper", 2, 3, "GPU device error")
            return ReconstructionResult(
                workspace_dir=tmp_path / "ws",
                sparse_dir=tmp_path / "ws" / "sparse",
                num_images=3,
                num_registered=3,
                num_points3d=50,
                steps_completed=[
                    "feature_extraction",
                    "exhaustive_matching",
                    "sparse_reconstruction",
                ],
            )

        job_dir, mock_job_store, mock_download, mock_extract, mock_redis = (
            _make_pipeline_mocks(tmp_path, "colmapretry2")
        )

        def mock_publish(channel, data):
            msg = json_mod.loads(data)
            if msg.get("progress", {}).get("stage") == "colmap_retry":
                captured_retry_messages.append(msg)

        mock_redis.publish.side_effect = mock_publish

        with (
            patch("src.api.tasks._get_redis", return_value=mock_redis),
            patch("src.api.tasks.JobStore", return_value=mock_job_store),
            patch("src.api.tasks._validate_job_path", return_value=job_dir),
            patch("src.downloader.download_video", mock_download),
            patch("src.extractor.extract_and_filter", mock_extract),
            patch("src.reconstruction.reconstruct", side_effect=mock_reconstruct),
        ):
            run_pipeline("colmapretry2", "https://youtu.be/dQw4w9WgXcQ")

        assert len(captured_retry_messages) == 1
        progress = captured_retry_messages[0]["progress"]
        assert progress["stage"] == "colmap_retry"
        assert progress["colmap_step"] == "mapper"
        assert progress["attempt"] == 2
        assert progress["max_retries"] == 3
        assert "재시도" in progress["message"]
