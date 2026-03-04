"""FastAPI 애플리케이션 및 API 엔드포인트."""

from __future__ import annotations

import logging
import uuid
from enum import StrEnum
from pathlib import Path
from threading import Thread
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.downloader import validate_youtube_url
from src.extractor import extract_and_filter
from src.reconstruction import reconstruct

logger = logging.getLogger(__name__)

app = FastAPI(title="EXTube API", version="0.1.0")

OUTPUT_BASE_DIR = Path("data/jobs")


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


# 인메모리 작업 저장소
_jobs: dict[str, dict[str, Any]] = {}


def _run_pipeline(job_id: str, params: JobCreate) -> None:
    """백그라운드에서 파이프라인을 실행한다."""
    from src.downloader import download_video

    job = _jobs[job_id]
    job["status"] = JobStatus.processing
    job_dir = OUTPUT_BASE_DIR / job_id

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

        job["status"] = JobStatus.completed
        job["result"] = {
            "video_title": download_result.title,
            "total_frames": extraction_result.total_extracted,
            "filtered_frames": extraction_result.total_filtered,
            "num_registered": reconstruction_result.num_registered,
            "num_points3d": reconstruction_result.num_points3d,
            "steps_completed": reconstruction_result.steps_completed,
        }

        # PLY 파일 경로 저장
        ply_path = reconstruction_dir / "points.ply"
        if ply_path.exists():
            job["ply_path"] = str(ply_path)

    except Exception as e:
        logger.exception("작업 %s 실패", job_id)
        job["status"] = JobStatus.failed
        job["error"] = str(e)


@app.post("/api/jobs", response_model=JobResponse, status_code=201)
def create_job(body: JobCreate) -> JobResponse:
    """복원 작업을 생성한다."""
    if not validate_youtube_url(body.url):
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 유튜브 URL: {body.url}",
        )

    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "id": job_id,
        "status": JobStatus.pending,
        "url": body.url,
        "error": None,
        "result": None,
    }

    thread = Thread(target=_run_pipeline, args=(job_id, body), daemon=True)
    thread.start()

    return JobResponse(
        id=job_id,
        status=JobStatus.pending,
        url=body.url,
    )


@app.get("/api/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str) -> JobResponse:
    """작업 상태를 조회한다."""
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
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")

    if job["status"] != JobStatus.completed:
        raise HTTPException(
            status_code=400,
            detail=f"작업이 완료되지 않았습니다 (상태: {job['status']})",
        )

    ply_path = job.get("ply_path")
    if not ply_path or not Path(ply_path).exists():
        raise HTTPException(
            status_code=404,
            detail="결과 파일을 찾을 수 없습니다",
        )

    return FileResponse(
        path=ply_path,
        media_type="application/octet-stream",
        filename="points.ply",
    )
