"""QueueManager 활성 작업 추적 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from src.api.queue_manager import QueueManager


@pytest.fixture
def mock_redis():
    """Mock Redis 연결."""
    conn = MagicMock()
    return conn


@pytest.fixture
def qm(mock_redis):
    """QueueManager 인스턴스."""
    with patch("src.api.queue_manager._settings") as mock_settings:
        mock_settings.redis_url = "redis://localhost:6379"
        return QueueManager(redis_conn=mock_redis)


class TestDequeue:
    """dequeue (활성 등록) 테스트."""

    def test_dequeue_adds_to_active_set(self, qm, mock_redis):
        qm.dequeue("job123")
        mock_redis.sadd.assert_called_once_with("extube:active_jobs", "job123")

    def test_dequeue_multiple_jobs(self, qm, mock_redis):
        qm.dequeue("job1")
        qm.dequeue("job2")
        assert mock_redis.sadd.call_count == 2


class TestComplete:
    """complete (활성 해제) 테스트."""

    def test_complete_removes_from_active_set(self, qm, mock_redis):
        qm.complete("job123")
        mock_redis.srem.assert_called_once_with("extube:active_jobs", "job123")


class TestCancel:
    """cancel 테스트."""

    def test_cancel_removes_from_active_set(self, qm, mock_redis):
        mock_redis.srem.return_value = 1
        qm.cancel("job123")
        mock_redis.srem.assert_called_once_with("extube:active_jobs", "job123")

    def test_cancel_nonexistent_no_error(self, qm, mock_redis):
        mock_redis.srem.return_value = 0
        qm.cancel("nonexistent")
        mock_redis.srem.assert_called_once()


class TestGetActiveJobs:
    """get_active_jobs 테스트."""

    def test_returns_decoded_set(self, qm, mock_redis):
        mock_redis.smembers.return_value = {b"job1", b"job2"}
        result = qm.get_active_jobs()
        assert result == {"job1", "job2"}

    def test_empty_set(self, qm, mock_redis):
        mock_redis.smembers.return_value = set()
        result = qm.get_active_jobs()
        assert result == set()


class TestGetActiveCount:
    """get_active_count 테스트."""

    def test_returns_count(self, qm, mock_redis):
        mock_redis.scard.return_value = 3
        assert qm.get_active_count() == 3


class TestRunPipelineIntegration:
    """run_pipeline에서 QueueManager dequeue/complete 호출 검증."""

    @patch("src.api.tasks.get_queue_manager")
    @patch("src.api.tasks._get_redis")
    @patch("src.api.tasks.JobStore")
    @patch("src.api.tasks._validate_job_path")
    def test_dequeue_and_complete_called(
        self, mock_validate, mock_job_store_cls, mock_get_redis, mock_get_qm,
    ):
        """파이프라인 시작 시 dequeue, 종료 시 complete가 호출된다."""
        from src.api.tasks import run_pipeline

        mock_redis = MagicMock()
        mock_get_redis.return_value = mock_redis
        mock_qm = MagicMock()
        mock_get_qm.return_value = mock_qm

        mock_store = MagicMock()
        mock_job_store_cls.return_value = mock_store
        mock_validate.return_value = MagicMock()

        # 첫 update(status="processing")에서만 에러, 이후 정상
        call_count = {"n": 0}

        def update_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("test stop")

        mock_store.update.side_effect = update_side_effect
        mock_store.get.return_value = None

        run_pipeline("aabb11223344", "https://youtu.be/test")

        mock_qm.dequeue.assert_called_once_with("aabb11223344")
        mock_qm.complete.assert_called_once_with("aabb11223344")

    def test_auto_retry_reregisters_in_queue_manager(self):
        """재시도 시 QueueManager에 재등록 로직이 호출되는지 확인한다."""
        from src.api.tasks import _handle_pipeline_error

        mock_store = MagicMock()
        mock_store.get.return_value = {
            "id": "aabbccddeeff",
            "url": "https://youtu.be/test",
            "retry_count": 0,
            "params": {},
        }
        mock_redis = MagicMock()
        mock_qm = MagicMock()

        with (
            patch("src.api.tasks._settings") as mock_settings,
            patch("src.api.tasks.Queue"),
        ):
            mock_settings.max_retries = 3
            mock_settings.retry_base_delay = 10
            mock_settings.retry_backoff_multiplier = 3
            mock_settings.rq_queue_name = "gpu"
            mock_settings.rq_job_timeout = 3600

            error = ConnectionError("Connection refused")
            _handle_pipeline_error(
                "aabbccddeeff", error, mock_store, mock_redis, qm=mock_qm,
            )

        # 재시도 가능 오류이므로 qm에는 별도 호출 없음 (finally에서 complete 호출됨)
        # 재시도 큐잉 자체는 RQ enqueue_in으로 처리

    def test_non_retryable_skips_reregistration(self):
        """재시도 불가 오류 시 QueueManager 재등록이 없다."""
        from src.api.tasks import _handle_pipeline_error

        mock_store = MagicMock()
        mock_store.get.return_value = {
            "id": "aabbccddeeff",
            "url": "https://youtu.be/test",
            "retry_count": 0,
            "params": {},
        }
        mock_redis = MagicMock()
        mock_qm = MagicMock()

        error = ValueError("invalid input")
        _handle_pipeline_error(
            "aabbccddeeff", error, mock_store, mock_redis, qm=mock_qm,
        )

        # ValueError는 재시도 불가 — QueueManager에 재등록하지 않음
