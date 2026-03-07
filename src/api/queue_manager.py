"""작업 큐 동시실행 제한 및 우선순위 스케줄링."""

from __future__ import annotations

import json
import logging
import threading
from enum import StrEnum
from typing import Any

import redis

from src.api.config import get_settings

logger = logging.getLogger(__name__)

_settings = get_settings()

# Redis 키
_QUEUE_KEY = "extube:job_queue"  # sorted set (score=priority+timestamp)
_ACTIVE_KEY = "extube:active_jobs"  # set
_JOB_META_KEY = "extube:job_meta:{job_id}"  # hash


class JobPriority(StrEnum):
    """작업 우선순위."""

    high = "high"
    normal = "normal"


_PRIORITY_SCORES = {
    JobPriority.high: 0,
    JobPriority.normal: 1_000_000_000,
}


class QueueManager:
    """Redis 기반 작업 큐 관리자."""

    def __init__(self, redis_conn: redis.Redis | None = None) -> None:
        self._conn = redis_conn or redis.from_url(_settings.redis_url)
        self._max_concurrent = _settings.queue_max_concurrent
        self._lock = threading.Lock()

    def enqueue(
        self,
        job_id: str,
        priority: JobPriority = JobPriority.normal,
    ) -> int:
        """작업을 큐에 추가하고 큐 위치를 반환한다."""
        import time

        score = _PRIORITY_SCORES[priority] + time.time()
        meta = {"job_id": job_id, "priority": priority.value}
        pipe = self._conn.pipeline()
        pipe.zadd(_QUEUE_KEY, {job_id: score})
        pipe.set(
            _JOB_META_KEY.format(job_id=job_id),
            json.dumps(meta, ensure_ascii=False),
            ex=86400,
        )
        pipe.execute()

        position = self._get_position(job_id)
        logger.info(
            "작업 큐 추가: %s (우선순위=%s, 위치=%d)",
            job_id, priority.value, position,
        )
        return position

    def dequeue(self) -> str | None:
        """큐에서 다음 작업을 꺼낸다. 동시실행 제한을 확인한다."""
        with self._lock:
            active_count = self._conn.scard(_ACTIVE_KEY)
            if active_count >= self._max_concurrent:
                return None

            members = self._conn.zrange(_QUEUE_KEY, 0, 0)
            if not members:
                return None

            job_id = members[0]
            if isinstance(job_id, bytes):
                job_id = job_id.decode()

            pipe = self._conn.pipeline()
            pipe.zrem(_QUEUE_KEY, job_id)
            pipe.sadd(_ACTIVE_KEY, job_id)
            pipe.execute()

            logger.info("작업 큐에서 꺼냄: %s", job_id)
            return job_id

    def complete(self, job_id: str) -> None:
        """작업 완료 처리. 활성 목록에서 제거한다."""
        pipe = self._conn.pipeline()
        pipe.srem(_ACTIVE_KEY, job_id)
        pipe.delete(_JOB_META_KEY.format(job_id=job_id))
        pipe.execute()

    def cancel(self, job_id: str) -> bool:
        """큐에서 작업을 제거한다. 제거 성공 시 True."""
        pipe = self._conn.pipeline()
        pipe.zrem(_QUEUE_KEY, job_id)
        pipe.srem(_ACTIVE_KEY, job_id)
        pipe.delete(_JOB_META_KEY.format(job_id=job_id))
        results = pipe.execute()
        removed = results[0] > 0 or results[1] > 0
        if removed:
            logger.info("작업 큐에서 제거: %s", job_id)
        return removed

    def get_status(self) -> dict[str, Any]:
        """큐 전체 상태를 반환한다."""
        pipe = self._conn.pipeline()
        pipe.zcard(_QUEUE_KEY)
        pipe.smembers(_ACTIVE_KEY)
        pipe.zrange(_QUEUE_KEY, 0, -1, withscores=True)
        results = pipe.execute()

        pending_count = results[0]
        active_jobs = {
            m.decode() if isinstance(m, bytes) else m
            for m in results[1]
        }
        waiting_jobs = []
        for member, score in results[2]:
            jid = (
                member.decode() if isinstance(member, bytes)
                else member
            )
            waiting_jobs.append({"job_id": jid, "position": len(waiting_jobs) + 1})

        return {
            "max_concurrent": self._max_concurrent,
            "active_count": len(active_jobs),
            "active_jobs": sorted(active_jobs),
            "pending_count": pending_count,
            "waiting_jobs": waiting_jobs,
        }

    def get_position(self, job_id: str) -> int | None:
        """작업의 큐 위치를 반환한다. 큐에 없으면 None."""
        pos = self._get_position(job_id)
        return pos if pos > 0 else None

    def _get_position(self, job_id: str) -> int:
        rank = self._conn.zrank(_QUEUE_KEY, job_id)
        if rank is None:
            return 0
        return rank + 1


_queue_manager: QueueManager | None = None


def get_queue_manager() -> QueueManager:
    """싱글턴 QueueManager를 반환한다."""
    global _queue_manager  # noqa: PLW0603
    if _queue_manager is None:
        _queue_manager = QueueManager()
    return _queue_manager
