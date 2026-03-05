"""Job 결과물 스토리지 정리 및 보존 정책."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from src.api.config import get_settings
from src.api.db import JobStore

logger = logging.getLogger(__name__)

# 중간 파일 패턴 — 복원 완료 후 삭제 가능한 디렉토리/파일
INTERMEDIATE_DIRS = [
    "reconstruction/dense",
    "reconstruction/sparse",
    "reconstruction/database.db",
    "extraction",
    "download",
]


def cleanup_intermediate_files(
    job_store: JobStore,
    jobs_dir: Path,
    ttl: float | None = None,
) -> int:
    """완료된 Job의 중간 파일을 정리한다.

    Args:
        job_store: JobStore 인스턴스
        jobs_dir: Job 출력 기본 디렉토리
        ttl: 중간 파일 보존 기간 (초). None이면 설정에서 가져온다.

    Returns:
        정리된 Job 수.
    """
    settings = get_settings()
    if ttl is None:
        ttl = settings.intermediate_ttl_seconds

    cutoff = time.time() - ttl
    jobs = job_store.get_completed_jobs_older_than(cutoff)
    cleaned = 0

    for job in jobs:
        job_dir = jobs_dir / job["id"]
        if not job_dir.is_dir():
            continue

        removed_any = False
        for pattern in INTERMEDIATE_DIRS:
            target = job_dir / pattern
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                removed_any = True
            elif target.is_file():
                target.unlink(missing_ok=True)
                removed_any = True

        if removed_any:
            cleaned += 1
            logger.info("중간 파일 정리 완료: job_id=%s", job["id"])

    return cleaned


def cleanup_expired_results(
    job_store: JobStore,
    jobs_dir: Path,
    ttl: float | None = None,
) -> int:
    """보존 기간이 지난 최종 결과물과 Job을 삭제한다.

    Args:
        job_store: JobStore 인스턴스
        jobs_dir: Job 출력 기본 디렉토리
        ttl: 최종 결과물 보존 기간 (초). None이면 설정에서 가져온다.

    Returns:
        삭제된 Job 수.
    """
    settings = get_settings()
    if ttl is None:
        ttl = settings.result_ttl_seconds

    cutoff = time.time() - ttl
    jobs = job_store.get_completed_jobs_older_than(cutoff)
    deleted = 0

    for job in jobs:
        job_dir = jobs_dir / job["id"]
        if job_dir.is_dir():
            shutil.rmtree(job_dir, ignore_errors=True)
        job_store.delete(job["id"])
        deleted += 1
        logger.info("만료된 결과물 삭제: job_id=%s", job["id"])

    return deleted


def run_storage_cleanup() -> dict[str, int]:
    """스토리지 정리 작업을 실행한다. RQ 태스크로 호출된다."""
    settings = get_settings()
    job_store = JobStore(settings.db_path)

    try:
        intermediate_cleaned = cleanup_intermediate_files(
            job_store, settings.output_base_dir
        )
        results_deleted = cleanup_expired_results(
            job_store, settings.output_base_dir
        )

        summary = {
            "intermediate_cleaned": intermediate_cleaned,
            "results_deleted": results_deleted,
        }
        logger.info("스토리지 정리 완료: %s", summary)
        return summary
    finally:
        job_store.close()
