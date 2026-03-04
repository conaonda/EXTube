"""FastAPI 애플리케이션 및 API 엔드포인트."""

from __future__ import annotations

import atexit
import logging
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.downloader import validate_youtube_url
from src.extractor import extract_and_filter
from src.reconstruction import reconstruct

logger = logging.getLogger(__name__)

app = FastAPI(title="EXTube API", version="0.1.0")

# CORS 설정 (개발 환경)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_BASE_DIR = Path("data/jobs")
STATIC_DIR = Path(__file__).resolve().parent.parent / "viewer" / "dist"

_MAX_WORKERS = 4


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


class JobResponse(BaseModel):
    """작업 응답."""

    id: str
    status: JobStatus
    url: str
    error: str | None = None
    result: dict[str, Any] | None = None


# 인메모리 작업 저장소 (Lock으로 동시 접근 보호)
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = Lock()

# ThreadPoolExecutor로 동시 작업 수 제한
_executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
atexit.register(_executor.shutdown, wait=True)


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
    if not str(job_dir).startswith(str(base_resolved)):
        raise ValueError("잘못된 경로")
    return job_dir


def _run_pipeline(job_id: str, params: JobCreate) -> None:
    """백그라운드에서 파이프라인을 실행한다."""
    from src.downloader import download_video

    with _jobs_lock:
        job = _jobs[job_id]
        job["status"] = JobStatus.processing

    job_dir = _validate_job_path(job_id)

    try:
        # 1. 다운로드
        download_dir = job_dir / "download"
        download_result = download_video(
            params.url, download_dir, max_height=params.max_height
        )

        # 2. 프레임 추출
        extraction_dir = job_dir / "extraction"
        extraction_result = extract_and_filter(
            download_result.video_path,
            extraction_dir,
            interval=params.frame_interval,
            blur_threshold=params.blur_threshold,
        )

        # 3. 3D 복원
        reconstruction_dir = job_dir / "reconstruction"
        frames_dir = extraction_dir / "frames"
        reconstruction_result = reconstruct(
            frames_dir,
            reconstruction_dir,
            camera_model=params.camera_model,
        )

        # PLY 파일 경로 검증
        ply_path = reconstruction_dir / "points.ply"
        ply_resolved = ply_path.resolve()
        base_resolved = OUTPUT_BASE_DIR.resolve()

        with _jobs_lock:
            job["status"] = JobStatus.completed
            job["result"] = {
                "video_title": download_result.title,
                "total_frames": extraction_result.total_extracted,
                "filtered_frames": extraction_result.total_filtered,
                "num_registered": reconstruction_result.num_registered,
                "num_points3d": reconstruction_result.num_points3d,
                "steps_completed": reconstruction_result.steps_completed,
            }
            if ply_path.exists() and str(ply_resolved).startswith(str(base_resolved)):
                job["ply_path"] = str(ply_resolved)

    except Exception as e:
        logger.exception("작업 %s 실패", job_id)
        with _jobs_lock:
            job["status"] = JobStatus.failed
            job["error"] = str(e)


@app.post("/api/jobs", response_model=JobResponse, status_code=201)
def create_job(body: JobCreate) -> JobResponse:
    """복원 작업을 생성한다."""
    if not validate_youtube_url(body.url):
        sanitized_url = _sanitize_for_message(body.url)
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 유튜브 URL: {sanitized_url}",
        )

    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "status": JobStatus.pending,
            "url": body.url,
            "error": None,
            "result": None,
        }

    _executor.submit(_run_pipeline, job_id, body)

    return JobResponse(
        id=job_id,
        status=JobStatus.pending,
        url=body.url,
    )


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    """작업 상태를 조회한다."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

    return JobResponse(
        id=job["id"],
        status=job["status"],
        url=job["url"],
        error=job.get("error"),
        result=job.get("result"),
    )


@app.get("/api/jobs/{job_id}/result")
def get_job_result(job_id: str) -> FileResponse:
    """복원 결과물(PLY)을 다운로드한다."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

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
    if not str(ply_resolved).startswith(str(base_resolved)):
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


def mount_static_files() -> None:
    """프론트엔드 빌드 결과물을 정적 파일로 서빙한다."""
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


mount_static_files()
