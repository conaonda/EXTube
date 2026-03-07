"""공통 테스트 픽스처."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_queue_manager():
    """QueueManager 싱글턴을 mock하여 Redis 연결을 방지한다."""
    mock_qm = MagicMock()
    mock_qm.enqueue.return_value = 1
    mock_qm.dequeue.return_value = None
    mock_qm.get_position.return_value = None
    mock_qm.cancel.return_value = True
    mock_qm.get_status.return_value = {
        "max_concurrent": 1,
        "active_count": 0,
        "active_jobs": [],
        "pending_count": 0,
        "waiting_jobs": [],
    }

    with (
        patch("src.api.routers.jobs.get_queue_manager", return_value=mock_qm),
        patch("src.api.tasks.get_queue_manager", return_value=mock_qm),
    ):
        yield mock_qm
