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
