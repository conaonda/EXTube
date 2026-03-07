"""작업(Job) CRUD 엔드포인트."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from enum import StrEnum
from typing import Any

import redis
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from rq import Queue
from rq.command import send_stop_job_command
from rq.job import Job as RQJob

from src.api.auth import get_current_user
from src.api.config import get_settings
from src.api.dependencies import (
    get_job_store,
    get_user_job,
    sanitize_for_message,
    validate_job_path,
)
from src.api.queue_manager import JobPriority, get_queue_manager
from src.api.tasks import run_pipeline
from src.downloader import fetch_video_metadata, validate_youtube_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["jobs"])

_settings = get_settings()
_SSE_TIMEOUT_SECONDS = _settings.sse_timeout_seconds


class JobStatus(StrEnum):
    """작업 상태."""

    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    retrying = "retrying"
    cancelled = "cancelled"


_VALID_CAMERA_MODELS = frozenset(
    {
        "SIMPLE_PINHOLE",
        "PINHOLE",
        "SIMPLE_RADIAL",
        "RADIAL",
        "OPENCV",
        "OPENCV_FISHEYE",
        "FULL_OPENCV",
        "SIMPLE_RADIAL_FISHEYE",
        "RADIAL_FISHEYE",
        "THIN_PRISM_FISHEYE",
    }
)


class JobCreate(BaseModel):
    """작업 생성 요청."""

    url: str = Field(
        description="유튜브 영상 URL",
        examples=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )
    max_height: int = Field(
        1080,
        description="다운로드 영상의 최대 높이 (px)",
    )
    frame_interval: float = Field(
        1.0,
        ge=0.1,
        le=300,
        description="프레임 추출 간격 (초, 0.1~300)",
    )
    blur_threshold: float = Field(
        100.0,
        ge=0,
        le=500,
        description="블러 필터링 임계값 (0~500, 낮을수록 엄격)",
    )
    camera_model: str = Field(
        "SIMPLE_RADIAL",
        description="COLMAP 카메라 모델",
    )
    dense: bool = Field(
        False,
        description="Dense reconstruction 수행 여부",
    )
    max_image_size: int = Field(
        0,
        description="COLMAP 입력 이미지 최대 크기 (0=제한 없음)",
    )
    gaussian_splatting: bool = Field(
        False,
        description="3D Gaussian Splatting 수행 여부",
    )
    gs_max_iterations: int | None = Field(
        None,
        ge=1,
        le=100_000,
        description="GS 최대 반복 횟수 (1~100,000)",
    )
    priority: str = Field(
        "normal",
        description="작업 우선순위 (normal/high)",
    )
    force_reprocess: bool = Field(
        False,
        description="기존 완료된 결과가 있어도 강제 재처리",
    )

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        if v not in ("normal", "high"):
            raise ValueError(
                f"우선순위는 normal 또는 high여야 합니다: {v}"
            )
        return v

    @field_validator("camera_model")
    @classmethod
    def validate_camera_model(cls, v: str) -> str:
        if v not in _VALID_CAMERA_MODELS:
            raise ValueError(
                f"지원하지 않는 카메라 모델: {v}. 허용: {sorted(_VALID_CAMERA_MODELS)}"
            )
        return v


class JobResponse(BaseModel):
    """작업 응답."""

    id: str = Field(description="작업 고유 ID", examples=["a1b2c3d4e5f6"])
    status: JobStatus = Field(description="작업 상태")
    url: str = Field(description="원본 유튜브 URL")
    error: str | None = Field(None, description="오류 메시지 (실패 시)")
    result: dict[str, Any] | None = Field(None, description="복원 결과 메타데이터")
    gs_splat_url: str | None = Field(None, description="Gaussian Splatting 파일 URL")
    retry_count: int = Field(0, description="재시도 횟수")
    queue_position: int | None = Field(None, description="큐 대기 위치 (대기 중일 때)")


class JobListResponse(BaseModel):
    """Job 목록 응답."""

    items: list[JobResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


def _get_redis_connection() -> redis.Redis:
    return redis.from_url(_settings.redis_url)


def _get_queue() -> Queue:
    return Queue(
        _settings.rq_queue_name,
        connection=_get_redis_connection(),
        default_timeout=_settings.rq_job_timeout,
    )


def _build_response(job: dict[str, Any]) -> JobResponse:
    """Job dict에서 JobResponse를 생성한다."""
    gs_splat_url = None
    if job.get("gs_splat_path"):
        gs_splat_url = f"/api/jobs/{job['id']}/splat"

    queue_position = None
    if job["status"] == JobStatus.pending:
        try:
            qm = get_queue_manager()
            queue_position = qm.get_position(job["id"])
        except Exception:
            pass

    return JobResponse(
        id=job["id"],
        status=job["status"],
        url=job["url"],
        error=job.get("error"),
        result=job.get("result"),
        gs_splat_url=gs_splat_url,
        retry_count=job.get("retry_count") or 0,
        queue_position=queue_position,
    )


def _enqueue_job(
    job_id: str,
    body: JobCreate,
    priority: JobPriority = JobPriority.normal,
) -> None:
    """RQ 큐에 파이프라인 태스크를 추가하고 대기 큐에 등록한다."""
    try:
        qm = get_queue_manager()
        qm.enqueue(job_id, priority=priority)
    except Exception:
        logger.warning("QueueManager enqueue 실패 (job_id=%s)", job_id)

    q = _get_queue()
    q.enqueue(
        run_pipeline,
        job_id=job_id,
        url=body.url,
        max_height=body.max_height,
        frame_interval=body.frame_interval,
        blur_threshold=body.blur_threshold,
        camera_model=body.camera_model,
        dense=body.dense,
        max_image_size=body.max_image_size,
        gaussian_splatting=body.gaussian_splatting,
        gs_max_iterations=body.gs_max_iterations,
        job_timeout=_settings.rq_job_timeout,
    )


_ALLOWED_SORT_FIELDS = {"created_at", "status", "url"}


@router.post(
    "/jobs",
    response_model=JobResponse,
    status_code=201,
    summary="복원 작업 생성",
)
def create_job(
    body: JobCreate,
    current_user: dict = Depends(get_current_user),
) -> JobResponse:
    """복원 작업을 생성한다."""
    store = get_job_store()

    if not validate_youtube_url(body.url):
        sanitized_url = sanitize_for_message(body.url)
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 유튜브 URL: {sanitized_url}",
        )

    try:
        meta = fetch_video_metadata(body.url)
    except RuntimeError as e:
        raise HTTPException(
            status_code=503,
            detail=f"영상 정보를 가져올 수 없습니다: {e}",
        )

    if meta.duration is None:
        raise HTTPException(
            status_code=422,
            detail="영상 길이를 확인할 수 없습니다 "
            "(라이브 스트림 등은 지원하지 않습니다)",
        )

    max_duration = _settings.max_video_duration_seconds
    if meta.duration > max_duration:
        minutes = int(meta.duration // 60)
        seconds = int(meta.duration % 60)
        limit_min = max_duration // 60
        raise HTTPException(
            status_code=422,
            detail=(
                f"영상 길이({minutes}분 {seconds}초)가 제한({limit_min}분)을 초과합니다"
            ),
        )

    max_filesize_bytes = _settings.max_video_filesize_mb * 1024 * 1024
    if meta.filesize_approx and meta.filesize_approx > max_filesize_bytes:
        size_mb = meta.filesize_approx / (1024 * 1024)
        raise HTTPException(
            status_code=422,
            detail=(
                f"예상 파일 크기({size_mb:.0f}MB)가 "
                f"제한({_settings.max_video_filesize_mb}MB)을 초과합니다"
            ),
        )

    if not body.force_reprocess:
        existing = store.find_completed_by_url(body.url, current_user["id"])
        if existing is not None:
            return JSONResponse(
                content=_build_response(existing).model_dump(mode="json"),
                status_code=200,
            )

    active_statuses = [JobStatus.pending, JobStatus.processing, JobStatus.retrying]
    active_count = 0
    for s in active_statuses:
        result = store.list(
            status=s.value,
            user_id=current_user["id"],
            limit=0,
        )
        active_count += result["total"]
    if active_count >= _settings.max_jobs_per_user:
        raise HTTPException(
            status_code=429,
            detail=f"동시 실행 제한 초과: 최대 {_settings.max_jobs_per_user}개",
        )

    job_id = uuid.uuid4().hex[:12]
    store.create(
        job_id,
        JobStatus.pending,
        body.url,
        user_id=current_user["id"],
    )
    params = {
        k: v
        for k, v in body.model_dump().items()
        if k not in ("url", "force_reprocess", "priority")
    }
    store.update(job_id, params=params)
    job_priority = JobPriority(body.priority)
    _enqueue_job(job_id, body, priority=job_priority)

    queue_position = None
    try:
        qm = get_queue_manager()
        queue_position = qm.get_position(job_id)
    except Exception:
        pass

    return JobResponse(
        id=job_id,
        status=JobStatus.pending,
        url=body.url,
        queue_position=queue_position,
    )


@router.get(
    "/jobs",
    response_model=JobListResponse,
    summary="작업 목록 조회",
)
def list_jobs(
    status: JobStatus | None = Query(None),
    page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
    per_page: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
    sort_by: str = Query("created_at", description="정렬 기준 컬럼"),
    order: str = Query("desc", description="정렬 방향 (asc/desc)"),
    current_user: dict = Depends(get_current_user),
) -> JobListResponse:
    """Job 목록을 조회한다. 본인의 Job만 반환한다."""
    store = get_job_store()

    if sort_by not in _ALLOWED_SORT_FIELDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"정렬 기준은 "
                f"{', '.join(sorted(_ALLOWED_SORT_FIELDS))} "
                f"중 하나여야 합니다"
            ),
        )
    if order not in ("asc", "desc"):
        raise HTTPException(
            status_code=422,
            detail="정렬 방향은 asc 또는 desc여야 합니다",
        )
    offset = (page - 1) * per_page
    result = store.list(
        status=status.value if status else None,
        limit=per_page,
        offset=offset,
        user_id=current_user["id"],
        sort_by=sort_by,
        order=order,
    )
    total = result["total"]
    total_pages = max(1, -(-total // per_page))
    return JobListResponse(
        items=[_build_response(j) for j in result["items"]],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    summary="작업 상태 조회",
)
def get_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> JobResponse:
    """작업 상태를 조회한다."""
    job = get_user_job(job_id, current_user)
    return _build_response(job)


@router.delete("/jobs/{job_id}", status_code=204, summary="작업 삭제")
def delete_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> None:
    """작업을 삭제하고 관련 파일을 정리한다."""
    import shutil

    store = get_job_store()
    job = get_user_job(job_id, current_user)

    if job["status"] in (JobStatus.processing, JobStatus.retrying):
        raise HTTPException(
            status_code=409,
            detail="처리 중인 작업은 삭제할 수 없습니다",
        )

    try:
        job_dir = validate_job_path(job_id)
        if job_dir.is_dir():
            shutil.rmtree(job_dir)
    except ValueError:
        pass

    store.delete(job_id)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=JobResponse,
    summary="실패한 작업 재시도",
)
def retry_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> JobResponse:
    """실패한 작업을 수동으로 재시도한다."""
    store = get_job_store()
    job = get_user_job(job_id, current_user)

    if job["status"] != JobStatus.failed:
        raise HTTPException(
            status_code=409,
            detail="실패한 작업만 재시도할 수 있습니다",
        )

    store.update(job_id, status="pending", error=None, retry_count=0)
    stored_params = job.get("params") or {}
    body = JobCreate(url=job["url"], **stored_params)
    _enqueue_job(job_id, body)

    updated_job = store.get(job_id)
    return _build_response(updated_job)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobResponse,
    summary="작업 취소",
)
def cancel_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> JobResponse:
    """진행 중인 작업을 취소한다."""
    import shutil

    store = get_job_store()
    job = get_user_job(job_id, current_user)

    cancellable = (
        JobStatus.pending,
        JobStatus.processing,
        JobStatus.retrying,
    )
    if job["status"] not in cancellable:
        raise HTTPException(
            status_code=409,
            detail=f"취소할 수 없는 상태입니다 (현재: {job['status']})",
        )

    # QueueManager 대기 큐/active set에서 제거
    try:
        qm = get_queue_manager()
        qm.cancel(job_id)
    except Exception:
        pass

    conn = _get_redis_connection()
    try:
        try:
            rq_job = RQJob.fetch(job_id, connection=conn)
            rq_job.cancel()
        except Exception:
            pass

        if job["status"] == JobStatus.processing:
            try:
                send_stop_job_command(conn, job_id)
            except Exception:
                pass

        store.update(
            job_id,
            status="cancelled",
            error="사용자에 의해 취소됨",
        )

        conn.publish(
            f"job:{job_id}:progress",
            json.dumps(
                {"status": "cancelled", "message": "사용자에 의해 취소됨"},
                ensure_ascii=False,
            ),
        )

        try:
            job_dir = validate_job_path(job_id)
            if job_dir.is_dir():
                shutil.rmtree(job_dir)
        except ValueError:
            pass
    finally:
        conn.close()

    updated = store.get(job_id)
    return _build_response(updated)


@router.get("/jobs/{job_id}/stream", summary="작업 진행률 SSE 스트림")
async def stream_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """SSE로 작업 진행률을 실시간 스트리밍한다."""
    get_user_job(job_id, current_user)
    store = get_job_store()

    async def event_generator():
        last_progress = None
        start_time = time.monotonic()
        try:
            while True:
                if time.monotonic() - start_time > _SSE_TIMEOUT_SECONDS:
                    timeout_data = {
                        "status": "timeout",
                        "message": "스트리밍 시간 초과",
                    }
                    yield (f"data: {json.dumps(timeout_data, ensure_ascii=False)}\n\n")
                    break

                current = store.get(job_id)
                if current is None:
                    break

                terminal = (
                    JobStatus.completed,
                    JobStatus.failed,
                    JobStatus.cancelled,
                )
                if current["status"] in terminal:
                    final_data = {
                        "status": current["status"],
                        "progress": current.get("progress"),
                        "result": current.get("result"),
                        "error": current.get("error"),
                    }
                    yield (f"data: {json.dumps(final_data, ensure_ascii=False)}\n\n")
                    break

                progress = current.get("progress")
                if progress != last_progress:
                    last_progress = progress
                    event_data = {
                        "status": current["status"],
                        "progress": progress,
                    }
                    yield (f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n")

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("SSE 연결 해제: job %s", job_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class QueueStatusResponse(BaseModel):
    """큐 상태 응답."""

    max_concurrent: int = Field(description="최대 동시 실행 수")
    active_count: int = Field(description="현재 실행 중인 작업 수")
    active_jobs: list[str] = Field(description="실행 중인 작업 ID")
    pending_count: int = Field(description="대기 중인 작업 수")
    waiting_jobs: list[dict[str, Any]] = Field(
        description="대기 중인 작업 목록",
    )


@router.get(
    "/queue/status",
    response_model=QueueStatusResponse,
    summary="큐 상태 조회",
)
def get_queue_status(
    current_user: dict = Depends(get_current_user),
) -> QueueStatusResponse:
    """작업 큐의 현재 상태를 반환한다."""
    qm = get_queue_manager()
    status = qm.get_status()
    return QueueStatusResponse(**status)
