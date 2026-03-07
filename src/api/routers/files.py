"""파일 서빙 엔드포인트."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from src.api import dependencies
from src.api.auth import get_current_user, get_current_user_or_query_token
from src.api.dependencies import (
    get_user_job,
    validate_job_path,
)

router = APIRouter(prefix="/api", tags=["jobs"])


class FileInfo(BaseModel):
    """파일 정보."""

    name: str
    size: int


class JobFilesResponse(BaseModel):
    """Job 파일 목록 응답."""

    job_id: str
    files: list[FileInfo]


@router.get(
    "/jobs/{job_id}/result",
    summary="복원 결과 PLY 다운로드",
)
def get_job_result(
    job_id: str,
    current_user: dict = Depends(get_current_user_or_query_token),
) -> FileResponse:
    """복원 결과물(PLY)을 다운로드한다."""
    job = get_user_job(job_id, current_user)

    if job["status"] != "completed":
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
    base_resolved = dependencies.get_output_base_dir().resolve()
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


@router.get(
    "/jobs/{job_id}/splat",
    summary="Gaussian Splatting 파일 다운로드",
)
def get_splat_file(
    job_id: str,
    current_user: dict = Depends(get_current_user_or_query_token),
) -> FileResponse:
    """Gaussian Splatting .ply/.splat 파일을 서빙한다."""
    job = get_user_job(job_id, current_user)

    if job["status"] != "completed":
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
    base_resolved = dependencies.get_output_base_dir().resolve()
    if not splat_resolved.is_relative_to(base_resolved):
        raise HTTPException(
            status_code=400,
            detail="잘못된 파일 경로입니다",
        )

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


@router.get(
    "/jobs/{job_id}/potree/{file_path:path}",
    summary="Potree octree 파일 서빙",
)
def get_potree_file(
    job_id: str,
    file_path: str,
    current_user: dict = Depends(get_current_user_or_query_token),
) -> FileResponse:
    """Potree octree 파일을 서빙한다."""
    job = get_user_job(job_id, current_user)

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"작업이 완료되지 않았습니다 (상태: {job['status']})",
        )

    potree_dir = job.get("potree_dir")
    if not potree_dir:
        raise HTTPException(
            status_code=404,
            detail="Potree 데이터를 찾을 수 없습니다",
        )

    base_resolved = dependencies.get_output_base_dir().resolve()
    potree_resolved = Path(potree_dir).resolve()
    if not potree_resolved.is_relative_to(base_resolved):
        raise HTTPException(
            status_code=400,
            detail="잘못된 파일 경로입니다",
        )

    target = (potree_resolved / file_path).resolve()
    if not target.is_relative_to(potree_resolved):
        raise HTTPException(
            status_code=400,
            detail="잘못된 파일 경로입니다",
        )

    if not target.exists():
        raise HTTPException(
            status_code=404,
            detail="파일을 찾을 수 없습니다",
        )

    content_types = {
        ".json": "application/json",
        ".bin": "application/octet-stream",
        ".las": "application/octet-stream",
        ".laz": "application/octet-stream",
    }
    media_type = content_types.get(
        target.suffix.lower(),
        "application/octet-stream",
    )
    return FileResponse(path=str(target), media_type=media_type)


@router.get(
    "/jobs/{job_id}/files",
    response_model=JobFilesResponse,
    summary="작업 결과 파일 목록",
)
def list_job_files(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> JobFilesResponse:
    """완료된 Job의 결과 디렉토리 내 파일 목록을 반환한다."""
    job = get_user_job(job_id, current_user)

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"작업이 완료되지 않았습니다 (상태: {job['status']})",
        )

    try:
        job_dir = validate_job_path(job_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="작업을 찾을 수 없습니다",
        )

    result_dir = job_dir / "reconstruction"
    if not result_dir.is_dir():
        return JobFilesResponse(job_id=job_id, files=[])

    files = []
    base_resolved = result_dir.resolve()
    for f in sorted(result_dir.rglob("*")):
        if f.is_file() and f.resolve().is_relative_to(base_resolved):
            rel = f.relative_to(result_dir)
            files.append(FileInfo(name=str(rel), size=f.stat().st_size))

    return JobFilesResponse(job_id=job_id, files=files)


@router.get(
    "/jobs/{job_id}/download/{file_path:path}",
    summary="결과 파일 다운로드",
)
def download_job_file(
    job_id: str,
    file_path: str,
    current_user: dict = Depends(get_current_user_or_query_token),
) -> FileResponse:
    """완료된 Job의 결과 파일을 다운로드한다."""
    job = get_user_job(job_id, current_user)

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"작업이 완료되지 않았습니다 (상태: {job['status']})",
        )

    try:
        job_dir = validate_job_path(job_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="작업을 찾을 수 없습니다",
        )

    result_dir = job_dir / "reconstruction"
    target = (result_dir / file_path).resolve()
    base_resolved = result_dir.resolve()

    if not target.is_relative_to(base_resolved):
        raise HTTPException(
            status_code=400,
            detail="잘못된 파일 경로입니다",
        )

    if not target.is_file():
        raise HTTPException(
            status_code=404,
            detail="파일을 찾을 수 없습니다",
        )

    return FileResponse(
        path=str(target),
        media_type="application/octet-stream",
        filename=target.name,
        headers={
            "Content-Disposition": f'attachment; filename="{target.name}"',
        },
    )


_MAX_ZIP_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB


@router.get(
    "/jobs/{job_id}/download-zip",
    summary="작업 결과물 ZIP 번들 다운로드",
)
def download_job_zip(
    job_id: str,
    current_user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """완료된 작업의 전체 결과물을 ZIP으로 묶어 다운로드한다."""
    job = get_user_job(job_id, current_user)

    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"작업이 완료되지 않았습니다 (상태: {job['status']})",
        )

    try:
        job_dir = validate_job_path(job_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="작업을 찾을 수 없습니다",
        )

    result_dir = job_dir / "reconstruction"
    if not result_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail="결과 디렉토리를 찾을 수 없습니다",
        )

    base_resolved = result_dir.resolve()
    files: list[tuple[Path, str]] = []
    total_size = 0
    for f in sorted(result_dir.rglob("*")):
        if f.is_file() and f.resolve().is_relative_to(base_resolved):
            total_size += f.stat().st_size
            if total_size > _MAX_ZIP_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="결과물 크기가 다운로드 제한(2GB)을 초과합니다",
                )
            rel = str(f.relative_to(result_dir))
            files.append((f, rel))

    if not files:
        raise HTTPException(
            status_code=404,
            detail="다운로드할 파일이 없습니다",
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path, arcname in files:
            zf.write(file_path, arcname)
    buf.seek(0)

    filename = f"extube_{job_id}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
