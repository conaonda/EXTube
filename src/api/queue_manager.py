"""작업 큐 관리 — 우선순위 스케줄링, 동시실행 제한, 활성 작업 추적.

Redis sorted set 기반 대기 큐와 active set으로 구성된다.
RQ가 작업 실행을 담당하고, QueueManager는 큐 상태를 추적한다.
"""

from __future__ import annotations

import logging
import time
from enum import StrEnum
from typing import Any

import redis

from src.api.config import get_settings

logger = logging.getLogger(__name__)

_settings = get_settings()

_QUEUE_KEY = "extube:job_queue"  # sorted set (score = priority_offset + timestamp)
_ACTIVE_KEY = "extube:active_jobs"  # set


class JobPriority(StrEnum):
    """작업 우선순위."""

    high = "high"
    normal = "normal"


_PRIORITY_SCORES = {
    JobPriority.high: 0,
    JobPriority.normal: 1_000_000_000,
}


class QueueManager:
    """Redis 기반 작업 큐 관리자.

    - 대기 큐: sorted set으로 우선순위 기반 순서 관리
    - active set: 현재 실행 중인 작업 추적
    - 동시실행 제한: active set 크기로 추적 (실제 제한은 RQ 워커 설정과 병행)
    """

    def __init__(
        self,
        redis_conn: redis.Redis | None = None,
        max_concurrent: int | None = None,
    ) -> None:
        self._conn = redis_conn or redis.from_url(_settings.redis_url)
        self._max_concurrent = max_concurrent or _settings.queue_max_concurrent

    def enqueue(
        self,
        job_id: str,
        priority: JobPriority = JobPriority.normal,
    ) -> int:
        """작업을 대기 큐에 추가하고 큐 위치를 반환한다."""
        score = _PRIORITY_SCORES[priority] + time.time()
        self._conn.zadd(_QUEUE_KEY, {job_id: score})
        position = self._get_position(job_id)
        logger.info(
            "작업 큐 추가: %s (우선순위=%s, 위치=%d)",
            job_id,
            priority.value,
            position,
        )
        return position

    def dequeue(self, job_id: str) -> None:
        """작업을 대기 큐에서 제거하고 active set에 등록한다."""
        pipe = self._conn.pipeline()
        pipe.zrem(_QUEUE_KEY, job_id)
        pipe.sadd(_ACTIVE_KEY, job_id)
        pipe.execute()
        logger.info("작업 활성 등록: %s", job_id)

    def complete(self, job_id: str) -> None:
        """작업을 active set에서 제거한다."""
        self._conn.srem(_ACTIVE_KEY, job_id)
        logger.info("작업 활성 해제: %s", job_id)

    def cancel(self, job_id: str) -> bool:
        """큐와 active set에서 작업을 제거한다. 제거 성공 시 True."""
        pipe = self._conn.pipeline()
        pipe.zrem(_QUEUE_KEY, job_id)
        pipe.srem(_ACTIVE_KEY, job_id)
        results = pipe.execute()
        removed = results[0] > 0 or results[1] > 0
        if removed:
            logger.info("작업 큐/활성에서 제거: %s", job_id)
        return removed

    def get_position(self, job_id: str) -> int | None:
        """작업의 큐 대기 위치를 반환한다. 큐에 없으면 None."""
        pos = self._get_position(job_id)
        return pos if pos > 0 else None

    def get_active_jobs(self) -> set[str]:
        """현재 활성 작업 ID 목록을 반환한다."""
        members = self._conn.smembers(_ACTIVE_KEY)
        return {m.decode() if isinstance(m, bytes) else m for m in members}

    def get_active_count(self) -> int:
        """현재 활성 작업 수를 반환한다."""
        return self._conn.scard(_ACTIVE_KEY)

    def get_status(self) -> dict[str, Any]:
        """큐 전체 상태를 반환한다."""
        pipe = self._conn.pipeline()
        pipe.zcard(_QUEUE_KEY)
        pipe.smembers(_ACTIVE_KEY)
        pipe.zrange(_QUEUE_KEY, 0, -1)
        results = pipe.execute()

        pending_count = results[0]
        active_jobs = {m.decode() if isinstance(m, bytes) else m for m in results[1]}
        waiting_jobs = []
        for member in results[2]:
            jid = member.decode() if isinstance(member, bytes) else member
            waiting_jobs.append({"job_id": jid, "position": len(waiting_jobs) + 1})

        return {
            "max_concurrent": self._max_concurrent,
            "active_count": len(active_jobs),
            "active_jobs": sorted(active_jobs),
            "pending_count": pending_count,
            "waiting_jobs": waiting_jobs,
        }

    def _get_position(self, job_id: str) -> int:
        rank = self._conn.zrank(_QUEUE_KEY, job_id)
        if rank is None:
            return 0
        return rank + 1


_queue_manager: QueueManager | None = None


def get_queue_manager(redis_conn: redis.Redis | None = None) -> QueueManager:
    """싱글턴 QueueManager를 반환한다.

    redis_conn이 전달되면 기존 싱글턴의 연결을 갱신한다.
    이는 RQ 워커에서 run_pipeline이 자체 Redis 연결을 사용할 때 필요하다.
    """
    global _queue_manager  # noqa: PLW0603
    if _queue_manager is None:
        _queue_manager = QueueManager(redis_conn=redis_conn)
    elif redis_conn is not None:
        _queue_manager._conn = redis_conn
    return _queue_manager
