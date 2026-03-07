"""작업 큐 활성 작업 추적 — RQ 워커 실행 흐름과 통합.

RQ 워커가 작업을 실행할 때 active set에 등록하고,
완료/실패 시 제거하여 활성 작업 상태를 정확히 추적한다.
"""

from __future__ import annotations

import logging

import redis

from src.api.config import get_settings

logger = logging.getLogger(__name__)

_settings = get_settings()

_ACTIVE_KEY = "extube:active_jobs"


class QueueManager:
    """Redis 기반 활성 작업 추적 관리자.

    RQ가 작업 큐잉과 실행을 담당하고, QueueManager는
    현재 실행 중인 작업의 active set을 관리한다.
    """

    def __init__(self, redis_conn: redis.Redis | None = None) -> None:
        self._conn = redis_conn or redis.from_url(_settings.redis_url)

    def dequeue(self, job_id: str) -> None:
        """작업을 active set에 등록한다. RQ 워커가 작업 실행 시작 시 호출."""
        self._conn.sadd(_ACTIVE_KEY, job_id)
        logger.info("작업 활성 등록: %s", job_id)

    def complete(self, job_id: str) -> None:
        """작업을 active set에서 제거한다. 작업 완료/실패 시 호출."""
        self._conn.srem(_ACTIVE_KEY, job_id)
        logger.info("작업 활성 해제: %s", job_id)

    def cancel(self, job_id: str) -> None:
        """취소된 작업을 active set에서 제거한다."""
        removed = self._conn.srem(_ACTIVE_KEY, job_id)
        if removed:
            logger.info("작업 취소 — 활성 해제: %s", job_id)

    def get_active_jobs(self) -> set[str]:
        """현재 활성 작업 ID 목록을 반환한다."""
        members = self._conn.smembers(_ACTIVE_KEY)
        return {m.decode() if isinstance(m, bytes) else m for m in members}

    def get_active_count(self) -> int:
        """현재 활성 작업 수를 반환한다."""
        return self._conn.scard(_ACTIVE_KEY)


_queue_manager: QueueManager | None = None


def get_queue_manager(redis_conn: redis.Redis | None = None) -> QueueManager:
    """싱글턴 QueueManager를 반환한다."""
    global _queue_manager  # noqa: PLW0603
    if _queue_manager is None:
        _queue_manager = QueueManager(redis_conn=redis_conn)
    return _queue_manager
