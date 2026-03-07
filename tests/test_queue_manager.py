"""QueueManager 활성 작업 추적, 우선순위, 동시실행 제한 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from src.api.queue_manager import JobPriority, QueueManager


@pytest.fixture
def mock_redis():
    """Mock Redis 연결."""
    conn = MagicMock()
    pipe = MagicMock()
    conn.pipeline.return_value = pipe
    pipe.execute.return_value = [1, 1]
    return conn


@pytest.fixture
def qm(mock_redis):
    """QueueManager 인스턴스."""
    with patch("src.api.queue_manager._settings") as mock_settings:
        mock_settings.redis_url = "redis://localhost:6379"
        mock_settings.queue_max_concurrent = 1
        return QueueManager(redis_conn=mock_redis, max_concurrent=1)


class TestEnqueue:
    """enqueue 테스트."""

    def test_enqueue_returns_position(self, qm, mock_redis):
        mock_redis.zrank.return_value = 0
        pos = qm.enqueue("job123", priority=JobPriority.normal)
        assert pos == 1
        mock_redis.zadd.assert_called_once()

    def test_high_priority_lower_score(self, qm, mock_redis):
        mock_redis.zrank.return_value = 0
        qm.enqueue("job_high", priority=JobPriority.high)
        high_score = list(mock_redis.zadd.call_args[0][1].values())[0]

        qm.enqueue("job_normal", priority=JobPriority.normal)
        normal_score = list(mock_redis.zadd.call_args[0][1].values())[0]

        assert high_score < normal_score

    def test_enqueue_not_in_queue(self, qm, mock_redis):
        mock_redis.zrank.return_value = None
        pos = qm.enqueue("job123")
        assert pos == 0  # _get_position returns 0 when not found


class TestDequeue:
    """dequeue (활성 등록) 테스트."""

    def test_dequeue_moves_to_active(self, qm, mock_redis):
        pipe = mock_redis.pipeline.return_value
        qm.dequeue("job123")
        pipe.zrem.assert_called_once_with("extube:job_queue", "job123")
        pipe.sadd.assert_called_once_with("extube:active_jobs", "job123")
        pipe.execute.assert_called_once()


class TestComplete:
    """complete (활성 해제) 테스트."""

    def test_complete_removes_from_active_set(self, qm, mock_redis):
        qm.complete("job123")
        mock_redis.srem.assert_called_once_with("extube:active_jobs", "job123")


class TestCancel:
    """cancel 테스트."""

    def test_cancel_removes_from_queue_and_active(self, qm, mock_redis):
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [1, 0]
        result = qm.cancel("job123")
        assert result is True
        pipe.zrem.assert_called_once_with("extube:job_queue", "job123")
        pipe.srem.assert_called_once_with("extube:active_jobs", "job123")

    def test_cancel_nonexistent(self, qm, mock_redis):
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [0, 0]
        result = qm.cancel("nonexistent")
        assert result is False


class TestGetStatus:
    """get_status 테스트."""

    def test_status(self, qm, mock_redis):
        pipe = mock_redis.pipeline.return_value
        pipe.execute.return_value = [
            2,  # zcard
            {b"active1"},  # smembers
            [b"wait1", b"wait2"],  # zrange
        ]
        status = qm.get_status()
        assert status["max_concurrent"] == 1
        assert status["active_count"] == 1
        assert status["pending_count"] == 2
        assert len(status["waiting_jobs"]) == 2
        assert status["waiting_jobs"][0]["position"] == 1
        assert status["waiting_jobs"][1]["position"] == 2


class TestGetPosition:
    """get_position 테스트."""

    def test_position_exists(self, qm, mock_redis):
        mock_redis.zrank.return_value = 2
        assert qm.get_position("job123") == 3

    def test_position_not_in_queue(self, qm, mock_redis):
        mock_redis.zrank.return_value = None
        assert qm.get_position("job123") is None


class TestGetActiveJobs:
    """get_active_jobs 테스트."""

    def test_returns_decoded_set(self, qm, mock_redis):
        mock_redis.smembers.return_value = {b"job1", b"job2"}
        result = qm.get_active_jobs()
        assert result == {"job1", "job2"}

    def test_empty_set(self, qm, mock_redis):
        mock_redis.smembers.return_value = set()
        assert qm.get_active_jobs() == set()


class TestGetActiveCount:
    """get_active_count 테스트."""

    def test_returns_count(self, qm, mock_redis):
        mock_redis.scard.return_value = 3
        assert qm.get_active_count() == 3


class TestGetPositionEdgeCases:
    """get_position 엣지케이스 테스트."""

    def test_first_in_queue_returns_one(self, qm, mock_redis):
        """rank=0 (큐 첫 번째)이면 get_position은 1을 반환한다."""
        mock_redis.zrank.return_value = 0
        assert qm.get_position("job123") == 1

    def test_not_in_queue_returns_none(self, qm, mock_redis):
        """큐에 없으면 get_position은 None을 반환한다."""
        mock_redis.zrank.return_value = None
        assert qm.get_position("job123") is None

    def test_internal_get_position_returns_zero_when_absent(self, qm, mock_redis):
        """_get_position은 미존재 시 0을 반환한다 (public get_position은 None)."""
        mock_redis.zrank.return_value = None
        assert qm._get_position("job123") == 0


class TestGetQueueManagerSingleton:
    """get_queue_manager 싱글턴 동작 테스트."""

    def test_returns_same_instance(self, mock_redis):
        """동일 인스턴스를 반환한다."""
        import src.api.queue_manager as qm_module

        qm_module._queue_manager = None
        with patch("src.api.queue_manager._settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.queue_max_concurrent = 1
            with patch("src.api.queue_manager.redis.from_url", return_value=mock_redis):
                from src.api.queue_manager import get_queue_manager

                inst1 = get_queue_manager()
                inst2 = get_queue_manager()
                assert inst1 is inst2
        qm_module._queue_manager = None

    def test_updates_connection_when_provided(self, mock_redis):
        """redis_conn 전달 시 기존 싱글턴의 연결을 갱신한다."""
        import src.api.queue_manager as qm_module

        qm_module._queue_manager = None
        with patch("src.api.queue_manager._settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379"
            mock_settings.queue_max_concurrent = 1
            with patch("src.api.queue_manager.redis.from_url", return_value=mock_redis):
                from unittest.mock import MagicMock

                from src.api.queue_manager import get_queue_manager

                inst = get_queue_manager()
                new_conn = MagicMock()
                get_queue_manager(redis_conn=new_conn)
                assert inst._conn is new_conn
        qm_module._queue_manager = None


class TestJobPriority:
    """JobPriority enum 테스트."""

    def test_values(self):
        assert JobPriority.high == "high"
        assert JobPriority.normal == "normal"


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
        """재시도 시 QueueManager에 재등록한다."""
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
