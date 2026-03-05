"""FastAPI 애플리케이션 및 API 엔드포인트."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum
from pathlib import Path
from typing import Any

import redis
from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from rq import Queue

from src.api.auth import get_current_user, set_job_store
from src.api.auth import router as auth_router
from src.api.config import get_settings
from src.api.db import JobStore
from src.api.rate_limit import RateLimitMiddleware, RateLimitRule
from src.api.tasks import run_pipeline
from src.api.ws import (
    start_redis_subscriber,
    stop_redis_subscriber,
    websocket_job_handler,
)
from src.downloader import validate_youtube_url

logger = logging.getLogger(__name__)

_settings = get_settings()


def _get_redis_connection() -> redis.Redis:
    return redis.from_url(_settings.redis_url)


def _get_queue() -> Queue:
    return Queue(
        _settings.rq_queue_name,
        connection=_get_redis_connection(),
        default_timeout=_settings.rq_job_timeout,
    )


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    """서버 시작 시 만료된 Job 정리 및 stale Job 복구."""
    deleted = _job_store.cleanup_expired(
        _settings.output_base_dir, ttl=_settings.job_ttl_seconds
    )
    if deleted:
        logger.info("만료된 Job %d개 정리됨", deleted)

    # 서버 재시작 시 미완료 Job을 failed로 전환
    recovered = _job_store.fail_stale_jobs(
        statuses=["pending", "processing"],
        error="서버 재시작으로 인해 작업이 중단되었습니다. 재제출해 주세요.",
    )
    if recovered:
        logger.info("재시작 복구: %d개 Job을 failed로 전환", recovered)

    # Redis pub/sub subscriber 시작
    start_redis_subscriber(_settings.redis_url)

    yield

    stop_redis_subscriber()


app = FastAPI(title="EXTube API", version="0.5.0", lifespan=_lifespan)

# 인증 라우터
app.include_router(auth_router)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting
app.add_middleware(
    RateLimitMiddleware,
    default_rule=RateLimitRule(max_requests=100, window_seconds=60),
    path_rules={
        ("POST", "/api/jobs"): RateLimitRule(max_requests=5, window_seconds=3600),
    },
)

OUTPUT_BASE_DIR = _settings.output_base_dir
STATIC_DIR = Path(__file__).resolve().parent.parent / "viewer" / "dist"

_SSE_TIMEOUT_SECONDS = _settings.sse_timeout_seconds


class JobStatus(StrEnum):
    """작업 상태."""

    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class JobCreate(BaseModel):
    """작업 생성 요청."""

    url: str
    max_height: int = 1080
    frame_interval: float = 1.0
    blur_threshold: float = 100.0
    camera_model: str = "SIMPLE_RADIAL"
    dense: bool = False
    max_image_size: int = 0
    gaussian_splatting: bool = False
    gs_max_iterations: int | None = None


class JobResponse(BaseModel):
    """작업 응답."""

    id: str
    status: JobStatus
    url: str
    error: str | None = None
    result: dict[str, Any] | None = None
    gs_splat_url: str | None = None


# Job 저장소 (SQLite)
_job_store = JobStore(db_path=_settings.db_path)
set_job_store(_job_store)


def _sanitize_for_message(value: str) -> str:
    """사용자 입력을 에러 메시지에 포함하기 전에 sanitize한다."""
    sanitized = re.sub(r"[<>&\"']", "", value)
    return sanitized[:200]


def _validate_job_path(job_id: str) -> Path:
    """job_id로부터 안전한 경로를 생성하고 path traversal을 방지한다."""
    if not re.fullmatch(r"[a-f0-9]{12}", job_id):
        raise ValueError(f"잘못된 job_id 형식: {job_id}")
    job_dir = (OUTPUT_BASE_DIR / job_id).resolve()
    base_resolved = OUTPUT_BASE_DIR.resolve()
    if not job_dir.is_relative_to(base_resolved):
        raise ValueError("잘못된 경로")
    return job_dir


def _enqueue_job(job_id: str, body: JobCreate) -> None:
    """RQ 큐에 파이프라인 태스크를 추가한다."""
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


# --- Health 엔드포인트 ---


@app.get("/health")
def health() -> dict[str, str]:
    """기본 헬스체크 — 서버 생존 확인."""
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready() -> dict[str, Any]:
    """준비 상태 확인 — DB 연결, Redis 연결 및 COLMAP 바이너리 존재 여부."""
    checks: dict[str, Any] = {}

    # DB 연결 확인
    try:
        _job_store.ping()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis 연결 확인
    try:
        conn = _get_redis_connection()
        conn.ping()
        conn.close()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # COLMAP 바이너리 확인
    colmap_path = shutil.which("colmap")
    checks["colmap"] = "ok" if colmap_path else "not found"

    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        raise HTTPException(status_code=503, detail=checks)

    return {"status": "ready", "checks": checks}


# --- Job 엔드포인트 ---


def _build_response(job: dict[str, Any]) -> JobResponse:
    """Job dict에서 JobResponse를 생성한다."""
    gs_splat_url = None
    if job.get("gs_splat_path"):
        gs_splat_url = f"/api/jobs/{job['id']}/splat"
    return JobResponse(
        id=job["id"],
        status=job["status"],
        url=job["url"],
        error=job.get("error"),
        result=job.get("result"),
        gs_splat_url=gs_splat_url,
    )


@app.post("/api/jobs", response_model=JobResponse, status_code=201)
def create_job(
    body: JobCreate,
    current_user: dict = Depends(get_current_user),
) -> JobResponse:
    """복원 작업을 생성한다."""
    if not validate_youtube_url(body.url):
        sanitized_url = _sanitize_for_message(body.url)
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 유튜브 URL: {sanitized_url}",
        )

    # 사용자별 동시 실행 제한 확인
    active_statuses = [JobStatus.pending, JobStatus.processing]
    active_count = 0
    for s in active_statuses:
        result = _job_store.list(status=s.value, user_id=current_user["id"], limit=0)
        active_count += result["total"]
    if active_count >= _settings.max_jobs_per_user:
        raise HTTPException(
            status_code=429,
            detail=f"동시 실행 제한 초과: 최대 {_settings.max_jobs_per_user}개",
        )

    job_id = uuid.uuid4().hex[:12]
    _job_store.create(job_id, JobStatus.pending, body.url, user_id=current_user["id"])

    _enqueue_job(job_id, body)

    return JobResponse(
        id=job_id,
        status=JobStatus.pending,
        url=body.url,
    )


class JobListResponse(BaseModel):
    """Job 목록 응답."""

    items: list[JobResponse]
    total: int


@app.get("/api/jobs", response_model=JobListResponse)
def list_jobs(
    status: JobStatus | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
) -> JobListResponse:
    """Job 목록을 조회한다. 본인의 Job만 반환한다."""
    result = _job_store.list(
        status=status.value if status else None,
        limit=limit,
        offset=offset,
        user_id=current_user["id"],
    )
    return JobListResponse(
        items=[_build_response(j) for j in result["items"]],
        total=result["total"],
    )


def _get_user_job(job_id: str, current_user: dict) -> dict:
    """Job을 조회하고 소유권을 확인한다."""
    job = _job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.get("user_id") is not None and job["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")
    return job


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> JobResponse:
    """작업 상태를 조회한다."""
    job = _get_user_job(job_id, current_user)
    return _build_response(job)


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> None:
    """작업을 삭제하고 관련 파일을 정리한다."""
    job = _get_user_job(job_id, current_user)

    if job["status"] == JobStatus.processing:
        raise HTTPException(
            status_code=409,
            detail="처리 중인 작업은 삭제할 수 없습니다",
        )

    # 디스크 파일 정리
    try:
        job_dir = _validate_job_path(job_id)
        if job_dir.is_dir():
            shutil.rmtree(job_dir)
    except ValueError:
        pass  # 잘못된 job_id 형식이면 디스크 정리 건너뜀

    _job_store.delete(job_id)


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """SSE로 작업 진행률을 실시간 스트리밍한다."""
    _get_user_job(job_id, current_user)

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
                    yield f"data: {json.dumps(timeout_data, ensure_ascii=False)}\n\n"
                    break

                current = _job_store.get(job_id)
                if current is None:
                    break

                if current["status"] in (JobStatus.completed, JobStatus.failed):
                    final_data = {
                        "status": current["status"],
                        "progress": current.get("progress"),
                        "result": current.get("result"),
                        "error": current.get("error"),
                    }
                    yield f"data: {json.dumps(final_data, ensure_ascii=False)}\n\n"
                    break

                progress = current.get("progress")
                if progress != last_progress:
                    last_progress = progress
                    event_data = {
                        "status": current["status"],
                        "progress": progress,
                    }
                    yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"

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


@app.get("/api/jobs/{job_id}/result")
def get_job_result(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> FileResponse:
    """복원 결과물(PLY)을 다운로드한다."""
    job = _get_user_job(job_id, current_user)

    if job["status"] != JobStatus.completed:
        raise HTTPException(
            status_code=400,
            detail=f"작업이 완료되지 않았습니다 (상태: {job['status']})",
        )

    ply_path = job.get("ply_path")
    if not ply_path:
        raise HTTPException(
            status_code=404,
            detail="결과 파일을 찾을 수 없습니다",
        )

    ply_resolved = Path(ply_path).resolve()
    base_resolved = OUTPUT_BASE_DIR.resolve()
    if not ply_resolved.is_relative_to(base_resolved):
        raise HTTPException(
            status_code=400,
            detail="잘못된 파일 경로입니다",
        )

    if not ply_resolved.exists():
        raise HTTPException(
            status_code=404,
            detail="결과 파일을 찾을 수 없습니다",
        )

    return FileResponse(
        path=str(ply_resolved),
        media_type="application/x-ply",
        filename="points.ply",
    )


@app.get("/api/jobs/{job_id}/splat")
def get_splat_file(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> FileResponse:
    """Gaussian Splatting .ply/.splat 파일을 서빙한다."""
    job = _get_user_job(job_id, current_user)

    if job["status"] != JobStatus.completed:
        raise HTTPException(
            status_code=400,
            detail=f"작업이 완료되지 않았습니다 (상태: {job['status']})",
        )

    gs_splat_path = job.get("gs_splat_path")
    if not gs_splat_path:
        raise HTTPException(
            status_code=404,
            detail="Gaussian Splatting 결과를 찾을 수 없습니다",
        )

    splat_resolved = Path(gs_splat_path).resolve()
    base_resolved = OUTPUT_BASE_DIR.resolve()
    if not splat_resolved.is_relative_to(base_resolved):
        raise HTTPException(status_code=400, detail="잘못된 파일 경로입니다")

    if not splat_resolved.exists():
        raise HTTPException(
            status_code=404,
            detail="Gaussian Splatting 결과 파일을 찾을 수 없습니다",
        )

    return FileResponse(
        path=str(splat_resolved),
        media_type="application/octet-stream",
        filename=splat_resolved.name,
    )


@app.get("/api/jobs/{job_id}/potree/{file_path:path}")
def get_potree_file(
    job_id: str,
    file_path: str,
    current_user: dict = Depends(get_current_user),
) -> FileResponse:
    """Potree octree 파일을 서빙한다."""
    job = _get_user_job(job_id, current_user)

    if job["status"] != JobStatus.completed:
        raise HTTPException(
            status_code=400,
            detail=f"작업이 완료되지 않았습니다 (상태: {job['status']})",
        )

    potree_dir = job.get("potree_dir")
    if not potree_dir:
        raise HTTPException(status_code=404, detail="Potree 데이터를 찾을 수 없습니다")

    base_resolved = OUTPUT_BASE_DIR.resolve()
    potree_resolved = Path(potree_dir).resolve()
    if not potree_resolved.is_relative_to(base_resolved):
        raise HTTPException(status_code=400, detail="잘못된 파일 경로입니다")

    target = (potree_resolved / file_path).resolve()
    if not target.is_relative_to(potree_resolved):
        raise HTTPException(status_code=400, detail="잘못된 파일 경로입니다")

    if not target.exists():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

    content_types = {
        ".json": "application/json",
        ".bin": "application/octet-stream",
        ".las": "application/octet-stream",
        ".laz": "application/octet-stream",
    }
    media_type = content_types.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(path=str(target), media_type=media_type)


@app.get("/api/jobs/{job_id}/files")
def list_job_files(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """완료된 Job의 결과 디렉토리 내 파일 목록을 반환한다."""
    job = _get_user_job(job_id, current_user)

    if job["status"] != JobStatus.completed:
        raise HTTPException(
            status_code=400,
            detail=f"작업이 완료되지 않았습니다 (상태: {job['status']})",
        )

    try:
        job_dir = _validate_job_path(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

    result_dir = job_dir / "reconstruction"
    if not result_dir.is_dir():
        return {"job_id": job_id, "files": []}

    files = []
    base_resolved = result_dir.resolve()
    for f in sorted(result_dir.rglob("*")):
        if f.is_file() and f.resolve().is_relative_to(base_resolved):
            rel = f.relative_to(result_dir)
            files.append(
                {
                    "name": str(rel),
                    "size": f.stat().st_size,
                }
            )

    return {"job_id": job_id, "files": files}


@app.get("/api/jobs/{job_id}/download/{file_path:path}")
def download_job_file(
    job_id: str,
    file_path: str,
    current_user: dict = Depends(get_current_user),
) -> FileResponse:
    """완료된 Job의 결과 파일을 다운로드한다."""
    job = _get_user_job(job_id, current_user)

    if job["status"] != JobStatus.completed:
        raise HTTPException(
            status_code=400,
            detail=f"작업이 완료되지 않았습니다 (상태: {job['status']})",
        )

    try:
        job_dir = _validate_job_path(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

    result_dir = job_dir / "reconstruction"
    target = (result_dir / file_path).resolve()
    base_resolved = result_dir.resolve()

    if not target.is_relative_to(base_resolved):
        raise HTTPException(status_code=400, detail="잘못된 파일 경로입니다")

    if not target.is_file():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")

    return FileResponse(
        path=str(target),
        media_type="application/octet-stream",
        filename=target.name,
        headers={"Content-Disposition": f'attachment; filename="{target.name}"'},
    )


@app.websocket("/ws/jobs/{job_id}")
async def ws_job_progress(websocket: WebSocket, job_id: str) -> None:
    """WebSocket으로 작업 진행률을 실시간 전달한다."""
    await websocket_job_handler(websocket, job_id, _job_store)


def mount_static_files() -> None:
    """프론트엔드 빌드 결과물을 정적 파일로 서빙한다."""
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


mount_static_files()
