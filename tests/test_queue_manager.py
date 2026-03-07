"""작업 큐 동시실행 제한 및 우선순위 스케줄링 테스트."""

from unittest.mock import MagicMock, patch

import pytest
from src.api.queue_manager import JobPriority, QueueManager


@pytest.fixture
def mock_redis():
    """Mock Redis 연결."""
    conn = MagicMock()
    pipe = MagicMock()
    conn.pipeline.return_value = pipe
    pipe.execute.return_value = [1, 1, 1]
    return conn


@pytest.fixture
def qm(mock_redis):
    """QueueManager 인스턴스."""
    with patch("src.api.queue_manager._settings") as mock_settings:
        mock_settings.queue_max_concurrent = 1
        mock_settings.redis_url = "redis://localhost:6379"
        return QueueManager(redis_conn=mock_redis)


class TestQueueManagerEnqueue:
    """enqueue 테스트."""

    def test_enqueue_returns_position(self, qm, mock_redis):
        mock_redis.zrank.return_value = 0
        pos = qm.enqueue("job123", priority=JobPriority.normal)
        assert pos == 1
        mock_redis.pipeline.assert_called()

    def test_high_priority_lower_score_than_normal(
        self,
        qm,
        mock_redis,
    ):
        mock_redis.zrank.return_value = 0
        qm.enqueue("job_high", priority=JobPriority.high)
        pipe = mock_redis.pipeline.return_value
        high_score = list(pipe.zadd.call_args[0][1].values())[0]

        qm.enqueue("job_normal", priority=JobPriority.normal)
        normal_score = list(pipe.zadd.call_args[0][1].values())[0]

        # high priority should have lower score (processed first)
        assert high_score < normal_score


class TestQueueManagerDequeue:
    """dequeue 테스트."""

    def test_dequeue_when_under_limit(self, qm, mock_redis):
        mock_redis.scard.return_value = 0
        mock_redis.zrange.return_value = [b"job123"]
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [1, 1]

        result = qm.dequeue()
        assert result == "job123"

    def test_dequeue_blocked_by_concurrency(self, qm, mock_redis):
        mock_redis.scard.return_value = 1  # max_concurrent=1
        result = qm.dequeue()
        assert result is None

    def test_dequeue_empty_queue(self, qm, mock_redis):
        mock_redis.scard.return_value = 0
        mock_redis.zrange.return_value = []
        result = qm.dequeue()
        assert result is None


class TestQueueManagerComplete:
    """complete 테스트."""

    def test_complete_removes_from_active(self, qm, mock_redis):
        pipe = mock_redis.pipeline.return_value
        qm.complete("job123")
        pipe.srem.assert_called()
        pipe.delete.assert_called()


class TestQueueManagerCancel:
    """cancel 테스트."""

    def test_cancel_removes_from_queue(self, qm, mock_redis):
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [1, 0, 1]
        result = qm.cancel("job123")
        assert result is True

    def test_cancel_nonexistent(self, qm, mock_redis):
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [0, 0, 0]
        result = qm.cancel("nonexistent")
        assert result is False


class TestQueueManagerStatus:
    """get_status 테스트."""

    def test_status(self, qm, mock_redis):
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [
            2,  # zcard
            {b"active1"},  # smembers
            [(b"wait1", 100.0), (b"wait2", 200.0)],  # zrange
        ]
        status = qm.get_status()
        assert status["max_concurrent"] == 1
        assert status["active_count"] == 1
        assert status["pending_count"] == 2
        assert len(status["waiting_jobs"]) == 2
        assert status["waiting_jobs"][0]["position"] == 1
        assert status["waiting_jobs"][1]["position"] == 2


class TestQueueManagerPosition:
    """get_position 테스트."""

    def test_position_exists(self, qm, mock_redis):
        mock_redis.zrank.return_value = 2
        assert qm.get_position("job123") == 3

    def test_position_not_in_queue(self, qm, mock_redis):
        mock_redis.zrank.return_value = None
        assert qm.get_position("job123") is None


class TestJobPriority:
    """JobPriority enum 테스트."""

    def test_values(self):
        assert JobPriority.high == "high"
        assert JobPriority.normal == "normal"


class TestQueueManagerDequeueActivatesWrongJob:
    """dequeue()가 실행 중인 job_id가 아닌 큐의 첫 항목을 활성화하는 버그 문서화.

    Reviewer 지적 (Critical): tasks.py에서 qm.dequeue()의 반환값을 사용하지 않아
    실행 중인 job_id가 아닌 큐의 첫 번째 항목이 active set에 등록될 수 있다.
    올바른 수정 방향: dequeue() 대신 activate(job_id) 메서드를 사용해야 한다.
    """

    def test_dequeue_activates_first_queue_item_not_executing_job(self, mock_redis):
        """dequeue()는 실행 중인 job_id가 아닌 큐의 첫 항목을 활성화한다."""
        with patch("src.api.queue_manager._settings") as mock_settings:
            mock_settings.queue_max_concurrent = 2
            mock_settings.redis_url = "redis://localhost:6379"
            qm = QueueManager(redis_conn=mock_redis)

        executing_job_id = "executing_job"
        queued_other_job = b"other_job"

        mock_redis.scard.return_value = 0
        mock_redis.zrange.return_value = [queued_other_job]  # 큐의 첫 항목은 다른 job
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [1, 1]

        # dequeue()가 반환하는 job_id는 실행 중인 job이 아닐 수 있다
        dequeued = qm.dequeue()
        assert dequeued == "other_job"
        assert dequeued != executing_job_id  # 실행 중인 job과 다름

        # complete()는 executing_job_id로 호출되지만
        # active set에는 "other_job"이 등록되어 있으므로 정리가 안 됨
        # 이로 인해 "other_job"이 active set에 영구 잔류할 수 있음

    def test_dequeue_return_value_ignored_means_no_concurrency_enforcement(
        self, mock_redis
    ):
        """dequeue() 반환값을 무시하면 동시실행 제한이 실질적으로 동작하지 않는다.

        tasks.py:96에서 qm.dequeue() 호출 후 반환값을 사용하지 않으므로,
        dequeue()가 None을 반환해도(동시실행 한계 초과) 작업이 계속 진행된다.
        """
        with patch("src.api.queue_manager._settings") as mock_settings:
            mock_settings.queue_max_concurrent = 1
            mock_settings.redis_url = "redis://localhost:6379"
            qm = QueueManager(redis_conn=mock_redis)

        # 이미 동시실행 한계에 도달한 상태
        mock_redis.scard.return_value = 1  # max_concurrent=1 이미 도달
        result = qm.dequeue()
        assert result is None  # 동시실행 제한으로 None 반환

        # tasks.py에서 반환값을 무시하므로 작업이 그냥 진행됨
        # (active 등록 없이 run_pipeline이 실행됨)


class TestRunPipelineQueueManagerIntegration:
    """run_pipeline과 QueueManager 통합 검증 테스트."""

    def _make_mocks(self, tmp_path, job_id):
        """run_pipeline 테스트용 공통 mock 설정."""
        from unittest.mock import MagicMock

        job_dir = tmp_path / "jobs" / job_id
        frames_dir = job_dir / "extraction" / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        mock_job_store = MagicMock()
        mock_download = MagicMock()
        mock_download.return_value.title = "Test"
        mock_download.return_value.video_path = tmp_path / "v.mp4"

        mock_extract = MagicMock()
        mock_extract.return_value.total_extracted = 3
        mock_extract.return_value.total_filtered = 0

        mock_redis = MagicMock()
        return job_dir, mock_job_store, mock_download, mock_extract, mock_redis

    def test_run_pipeline_calls_dequeue_once(self, tmp_path, mock_queue_manager):
        """run_pipeline 실행 시 qm.dequeue()를 정확히 1회 호출한다."""
        from unittest.mock import MagicMock, patch

        from src.api.tasks import run_pipeline
        from src.reconstruction.reconstruction import ReconstructionResult

        job_id = "aabbccddeeff"
        job_dir, mock_job_store, mock_download, mock_extract, mock_redis = (
            self._make_mocks(tmp_path, job_id)
        )

        mock_reconstruct = MagicMock(
            return_value=ReconstructionResult(
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
        )

        with (
            patch("src.api.tasks._get_redis", return_value=mock_redis),
            patch("src.api.tasks.JobStore", return_value=mock_job_store),
            patch("src.api.tasks._validate_job_path", return_value=job_dir),
            patch("src.downloader.download_video", mock_download),
            patch("src.extractor.extract_and_filter", mock_extract),
            patch("src.reconstruction.reconstruct", mock_reconstruct),
        ):
            run_pipeline(job_id, "https://youtu.be/test")

        mock_queue_manager.dequeue.assert_called_once()

    def test_run_pipeline_calls_complete_in_finally_on_success(
        self, tmp_path, mock_queue_manager
    ):
        """성공 시 finally 블록에서 qm.complete(job_id)를 호출한다."""
        from unittest.mock import MagicMock, patch

        from src.api.tasks import run_pipeline
        from src.reconstruction.reconstruction import ReconstructionResult

        job_id = "aabbccddeeff"
        job_dir, mock_job_store, mock_download, mock_extract, mock_redis = (
            self._make_mocks(tmp_path, job_id)
        )

        mock_reconstruct = MagicMock(
            return_value=ReconstructionResult(
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
        )

        with (
            patch("src.api.tasks._get_redis", return_value=mock_redis),
            patch("src.api.tasks.JobStore", return_value=mock_job_store),
            patch("src.api.tasks._validate_job_path", return_value=job_dir),
            patch("src.downloader.download_video", mock_download),
            patch("src.extractor.extract_and_filter", mock_extract),
            patch("src.reconstruction.reconstruct", mock_reconstruct),
        ):
            run_pipeline(job_id, "https://youtu.be/test")

        mock_queue_manager.complete.assert_called_once_with(job_id)

    def test_run_pipeline_calls_complete_in_finally_on_error(
        self, tmp_path, mock_queue_manager
    ):
        """예외 발생 시에도 finally 블록에서 qm.complete(job_id)를 호출한다."""
        from unittest.mock import MagicMock, patch

        from src.api.tasks import run_pipeline

        job_id = "aabbccddeeff"
        job_dir, mock_job_store, mock_download, mock_extract, mock_redis = (
            self._make_mocks(tmp_path, job_id)
        )

        # 재시도 불가 오류를 발생시켜 즉시 failed 처리
        mock_download.side_effect = ValueError("invalid url")
        mock_job_store.get.return_value = {
            "retry_count": 99,
            "url": "https://youtu.be/test",
            "params": {},
        }

        with (
            patch("src.api.tasks._get_redis", return_value=mock_redis),
            patch("src.api.tasks.JobStore", return_value=mock_job_store),
            patch("src.api.tasks._validate_job_path", return_value=job_dir),
            patch("src.downloader.download_video", mock_download),
        ):
            run_pipeline(job_id, "https://youtu.be/test")

        # 오류가 발생해도 finally에서 반드시 complete(job_id)가 호출되어야 함
        mock_queue_manager.complete.assert_called_once_with(job_id)

    def test_run_pipeline_complete_called_with_executing_job_id(
        self, tmp_path, mock_queue_manager
    ):
        """complete()는 실행 중인 job_id(run_pipeline 인자)로 호출되어야 한다.

        dequeue()가 다른 job_id를 반환하더라도,
        complete()는 항상 현재 실행 중인 job_id로 호출되어야 한다.
        """
        from unittest.mock import MagicMock, patch

        from src.api.tasks import run_pipeline
        from src.reconstruction.reconstruction import ReconstructionResult

        job_id = "aabbccddeeff"
        job_dir, mock_job_store, mock_download, mock_extract, mock_redis = (
            self._make_mocks(tmp_path, job_id)
        )

        # dequeue()가 다른 job_id를 반환하는 상황 시뮬레이션
        mock_queue_manager.dequeue.return_value = "different_job_id"

        mock_reconstruct = MagicMock(
            return_value=ReconstructionResult(
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
        )

        with (
            patch("src.api.tasks._get_redis", return_value=mock_redis),
            patch("src.api.tasks.JobStore", return_value=mock_job_store),
            patch("src.api.tasks._validate_job_path", return_value=job_dir),
            patch("src.downloader.download_video", mock_download),
            patch("src.extractor.extract_and_filter", mock_extract),
            patch("src.reconstruction.reconstruct", mock_reconstruct),
        ):
            run_pipeline(job_id, "https://youtu.be/test")

        # complete()는 dequeue()가 반환한 값이 아닌 실행 중인 job_id로 호출되어야 함
        mock_queue_manager.complete.assert_called_once_with(job_id)
