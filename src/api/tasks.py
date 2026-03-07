"""RQ 태스크: 파이프라인 실행 함수."""

from __future__ import annotations

import datetime
import json
import re
import time
from pathlib import Path
from typing import Any

import redis
from rq import Queue

from src.api.config import get_settings
from src.api.db import JobStore
from src.api.logging_config import get_logger
from src.api.queue_manager import QueueManager, get_queue_manager

logger = get_logger(__name__)

_settings = get_settings()

# 재시도 가능한 오류 패턴 (일시적 네트워크/외부 서비스 오류 및 COLMAP 일시적 오류)
_RETRYABLE_ERROR_PATTERNS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection refused",
    "temporary failure",
    "network is unreachable",
    "name resolution",
    "ssl",
    "http error 429",
    "http error 500",
    "http error 502",
    "http error 503",
    "http error 504",
    "unable to download",
    "urlopen error",
    "incompleteread",
    "remotedisconnected",
    "out of memory",
    "cuda",
    "gpu",
    "cannot allocate memory",
    "killed",
)


def is_retryable_error(error: Exception) -> bool:
    """오류가 재시도 가능한 일시적 오류인지 판별한다."""
    error_msg = str(error).lower()
    error_type = type(error).__name__.lower()
    combined = f"{error_type}: {error_msg}"
    return any(pattern in combined for pattern in _RETRYABLE_ERROR_PATTERNS)


def _get_redis() -> redis.Redis:
    return redis.from_url(_settings.redis_url)


def _publish_progress(
    redis_conn: redis.Redis, job_id: str, data: dict[str, Any]
) -> None:
    """Redis pub/sub 채널로 진행 상태를 발행한다."""
    redis_conn.publish(
        f"job:{job_id}:progress",
        json.dumps(data, ensure_ascii=False),
    )


def run_pipeline(
    job_id: str,
    url: str,
    max_height: int = 1080,
    frame_interval: float = 1.0,
    blur_threshold: float = 100.0,
    camera_model: str = "SIMPLE_RADIAL",
    dense: bool = False,
    max_image_size: int = 0,
    gaussian_splatting: bool = False,
    gs_max_iterations: int | None = None,
) -> None:
    """RQ worker에서 실행되는 파이프라인 태스크."""
    from src.downloader import download_video
    from src.extractor import extract_and_filter
    from src.reconstruction import reconstruct
    from src.reconstruction.reconstruction import ColmapRetryConfig

    job_store = JobStore(db_path=_settings.db_path)
    redis_conn = _get_redis()
    qm = get_queue_manager(redis_conn)

    # QueueManager에 활성 작업으로 등록
    qm.dequeue(job_id)

    output_base_dir = _settings.output_base_dir

    def _update_progress(stage: str, percent: int, message: str) -> None:
        progress = {"stage": stage, "percent": percent, "message": message}
        job_store.update(job_id, progress=progress)
        _publish_progress(
            redis_conn, job_id, {"status": "processing", "progress": progress}
        )

    try:
        job_store.update(job_id, status="processing")
        job_dir = _validate_job_path(job_id, output_base_dir)
        pipeline_start = time.monotonic()

        # 1. 다운로드
        _update_progress("download", 0, "영상 다운로드 시작")
        stage_start = time.monotonic()
        download_dir = job_dir / "download"
        download_result = download_video(url, download_dir, max_height=max_height)
        download_duration = round(time.monotonic() - stage_start, 2)
        logger.info(
            "stage_completed",
            job_id=job_id,
            stage="download",
            duration_s=download_duration,
        )
        _update_progress("download", 100, "영상 다운로드 완료")

        # 2. 프레임 추출
        _update_progress("extraction", 0, "프레임 추출 시작")
        stage_start = time.monotonic()
        extraction_dir = job_dir / "extraction"
        extraction_result = extract_and_filter(
            download_result.video_path,
            extraction_dir,
            interval=frame_interval,
            blur_threshold=blur_threshold,
        )
        extraction_duration = round(time.monotonic() - stage_start, 2)
        logger.info(
            "stage_completed",
            job_id=job_id,
            stage="extraction",
            duration_s=extraction_duration,
            total_extracted=extraction_result.total_extracted,
            total_filtered=extraction_result.total_filtered,
        )
        _update_progress("extraction", 100, "프레임 추출 완료")

        remaining = extraction_result.total_extracted - extraction_result.total_filtered
        if remaining < 2:
            raise ValueError(
                f"블러 필터링 후 사용 가능한 프레임이 부족합니다 "
                f"({remaining}장). 최소 2장이 필요합니다. "
                f"blur_threshold 값을 낮추거나 frame_interval을 줄여 보세요."
            )

        # 3. 3D 복원 (feature_matching → reconstruction → export)
        _update_progress("feature_matching", 0, "특징점 매칭 시작")
        stage_start = time.monotonic()
        reconstruction_dir = job_dir / "reconstruction"
        frames_dir = extraction_dir / "frames"

        colmap_retry_config = ColmapRetryConfig(
            max_retries=_settings.colmap_max_retries,
            base_delay=_settings.colmap_retry_base_delay,
            backoff_multiplier=_settings.colmap_retry_backoff_multiplier,
        )

        def _on_colmap_retry(
            step: str, attempt: int, max_retries: int, error_msg: str
        ) -> None:
            retry_progress = {
                "stage": "colmap_retry",
                "percent": 0,
                "message": f"COLMAP {step} 재시도 {attempt}/{max_retries}: {error_msg}",
                "colmap_step": step,
                "attempt": attempt,
                "max_retries": max_retries,
            }
            job_store.update(job_id, progress=retry_progress)
            _publish_progress(
                redis_conn,
                job_id,
                {"status": "processing", "progress": retry_progress},
            )

        reconstruction_result = reconstruct(
            frames_dir,
            reconstruction_dir,
            camera_model=camera_model,
            dense=dense,
            max_image_size=max_image_size,
            gaussian_splatting=gaussian_splatting,
            gs_max_iterations=gs_max_iterations,
            progress_callback=_update_progress,
            retry_config=colmap_retry_config,
            retry_callback=_on_colmap_retry,
        )
        reconstruction_duration = round(time.monotonic() - stage_start, 2)
        logger.info(
            "stage_completed",
            job_id=job_id,
            stage="reconstruction",
            duration_s=reconstruction_duration,
            num_registered=reconstruction_result.num_registered,
            num_points3d=reconstruction_result.num_points3d,
        )

        # PLY 파일 경로 검증
        ply_path = reconstruction_dir / "points.ply"
        ply_resolved = ply_path.resolve()
        base_resolved = output_base_dir.resolve()

        result: dict[str, Any] = {
            "video_title": download_result.title,
            "total_frames": extraction_result.total_extracted,
            "filtered_frames": extraction_result.total_filtered,
            "num_registered": reconstruction_result.num_registered,
            "num_points3d": reconstruction_result.num_points3d,
            "steps_completed": reconstruction_result.steps_completed,
        }
        if reconstruction_result.num_dense_points is not None:
            result["num_dense_points"] = reconstruction_result.num_dense_points
        if reconstruction_result.gs_num_iterations is not None:
            result["gs_num_iterations"] = reconstruction_result.gs_num_iterations

        updates: dict[str, Any] = {"status": "completed", "result": result}
        if ply_path.exists() and ply_resolved.is_relative_to(base_resolved):
            updates["ply_path"] = str(ply_resolved)

        dense_ply_path = reconstruction_dir / "dense_points.ply"
        if dense_ply_path.exists():
            dense_resolved = dense_ply_path.resolve()
            if dense_resolved.is_relative_to(base_resolved):
                updates["dense_ply_path"] = str(dense_resolved)

        gs_ply = reconstruction_result.gs_ply_path
        if gs_ply and gs_ply.exists():
            gs_resolved = gs_ply.resolve()
            if gs_resolved.is_relative_to(base_resolved):
                updates["gs_splat_path"] = str(gs_resolved)

        potree_meta = reconstruction_result.potree_metadata_path
        if potree_meta and potree_meta.exists():
            potree_dir = potree_meta.parent.resolve()
            if potree_dir.is_relative_to(base_resolved):
                updates["potree_dir"] = str(potree_dir)
                result["has_potree"] = True

        job_store.update(job_id, **updates)
        _publish_progress(redis_conn, job_id, {"status": "completed", "result": result})

        total_duration = round(time.monotonic() - pipeline_start, 2)
        logger.info(
            "pipeline_completed",
            job_id=job_id,
            total_duration_s=total_duration,
        )

    except Exception as e:
        _handle_pipeline_error(job_id, e, job_store, redis_conn, qm)
    finally:
        # 작업 완료/실패 시 active set에서 제거
        qm.complete(job_id)
        job_store.close()
        redis_conn.close()


def _handle_pipeline_error(
    job_id: str,
    error: Exception,
    job_store: JobStore,
    redis_conn: redis.Redis,
    qm: QueueManager | None = None,
) -> None:
    """파이프라인 오류를 처리하고 재시도 가능 여부를 판단한다."""
    job = job_store.get(job_id)
    retry_count = job.get("retry_count", 0) or 0 if job else 0

    if is_retryable_error(error) and retry_count < _settings.max_retries:
        new_retry_count = retry_count + 1
        delay = _settings.retry_base_delay * (
            _settings.retry_backoff_multiplier ** (new_retry_count - 1)
        )

        logger.warning(
            "pipeline_retrying",
            job_id=job_id,
            retry_count=new_retry_count,
            max_retries=_settings.max_retries,
            delay_s=delay,
            exc_type=type(error).__name__,
            exc_message=str(error),
        )

        job_store.update(
            job_id,
            status="retrying",
            retry_count=new_retry_count,
            error=f"재시도 {new_retry_count}/{_settings.max_retries}: {error}",
        )
        _publish_progress(
            redis_conn,
            job_id,
            {
                "status": "retrying",
                "retry_count": new_retry_count,
                "max_retries": _settings.max_retries,
                "next_retry_delay": delay,
                "error": str(error),
            },
        )

        # 지수 백오프 대기 후 재시도 큐잉
        q = Queue(
            _settings.rq_queue_name,
            connection=redis_conn,
            default_timeout=_settings.rq_job_timeout,
        )

        # Job의 원래 파라미터를 DB에서 복원하여 재큐잉
        if job:
            stored_params = job.get("params") or {}
            q.enqueue_in(
                time_delta=datetime.timedelta(seconds=delay),
                f=run_pipeline,
                job_id=job_id,
                url=job["url"],
                **stored_params,
                job_timeout=_settings.rq_job_timeout,
            )
    else:
        logger.error(
            "pipeline_failed",
            job_id=job_id,
            exc_type=type(error).__name__,
            exc_message=str(error),
            exc_info=error,
            retry_count=retry_count,
            retryable=is_retryable_error(error),
        )
        job_store.update(job_id, status="failed", error=str(error))
        _publish_progress(redis_conn, job_id, {"status": "failed", "error": str(error)})


def _validate_job_path(job_id: str, output_base_dir: Path) -> Path:
    """job_id로부터 안전한 경로를 생성하고 path traversal을 방지한다."""
    if not re.fullmatch(r"[a-f0-9]{12}", job_id):
        raise ValueError(f"잘못된 job_id 형식: {job_id}")
    job_dir = (output_base_dir / job_id).resolve()
    base_resolved = output_base_dir.resolve()
    if not job_dir.is_relative_to(base_resolved):
        raise ValueError("잘못된 경로")
    return job_dir
