"""헬스체크 및 메트릭 엔드포인트."""

from __future__ import annotations

import logging
import shutil
from typing import Any

import redis
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from prometheus_client import Gauge, generate_latest
from rq import Queue

from src.api.config import get_settings
from src.api.dependencies import get_job_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitoring"])

_settings = get_settings()

ACTIVE_JOBS_GAUGE = Gauge(
    "extube_active_jobs", "Number of active jobs (pending + processing)"
)
QUEUE_LENGTH_GAUGE = Gauge("extube_queue_length", "Number of jobs in the RQ queue")


def _update_job_gauges() -> None:
    """Scrape 시점에 활성 Job 수와 큐 길이를 갱신한다."""
    store = get_job_store()
    try:
        active = 0
        for s in ("pending", "processing", "retrying"):
            active += store.list(status=s, limit=0)["total"]
        ACTIVE_JOBS_GAUGE.set(active)
    except Exception as e:
        logger.warning("메트릭 게이지 업데이트 실패 (active_jobs): %s", e)
    try:
        conn = redis.from_url(
            _settings.redis_url, socket_connect_timeout=2, socket_timeout=2
        )
        q = Queue(
            _settings.rq_queue_name,
            connection=conn,
            default_timeout=_settings.rq_job_timeout,
        )
        QUEUE_LENGTH_GAUGE.set(len(q))
    except Exception as e:
        logger.warning("메트릭 게이지 업데이트 실패 (queue_length): %s", e)
        QUEUE_LENGTH_GAUGE.set(0)


@router.get("/health", summary="서버 상태 확인")
def health() -> dict[str, str]:
    """기본 헬스체크 — 하위 호환용."""
    return {"status": "ok"}


@router.get("/health/live", summary="생존 확인 (liveness probe)")
def health_live() -> dict[str, str]:
    """Liveness probe — 프로세스 생존 확인 (경량)."""
    return {"status": "alive"}


@router.get("/health/ready", summary="준비 상태 확인 (readiness probe)")
def health_ready() -> dict[str, Any]:
    """준비 상태 확인 — DB, Redis, COLMAP (readiness probe)."""
    store = get_job_store()
    checks: dict[str, Any] = {}

    try:
        store.ping()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    try:
        conn = redis.from_url(_settings.redis_url)
        conn.ping()
        conn.close()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    colmap_path = shutil.which("colmap")
    checks["colmap"] = "ok" if colmap_path else "not found"

    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        raise HTTPException(status_code=503, detail=checks)

    return {"status": "ready", "checks": checks}


@router.get("/metrics", include_in_schema=True)
def metrics() -> Response:
    """Prometheus 메트릭 엔드포인트."""
    _update_job_gauges()
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
