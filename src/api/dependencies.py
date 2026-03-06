"""공유 의존성 및 유틸리티."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from src.api.config import get_settings
from src.api.db import JobStore

_settings = get_settings()

# Job 저장소 (main.py에서 초기화)
_job_store: JobStore | None = None
OUTPUT_BASE_DIR: Path = _settings.output_base_dir


def init_job_store(store: JobStore) -> None:
    global _job_store  # noqa: PLW0603
    _job_store = store


def get_job_store() -> JobStore:
    assert _job_store is not None
    return _job_store


def sanitize_for_message(value: str) -> str:
    """사용자 입력을 에러 메시지에 포함하기 전에 sanitize한다."""
    sanitized = re.sub(r"[<>&\"']", "", value)
    return sanitized[:200]


def validate_job_path(job_id: str) -> Path:
    """job_id로부터 안전한 경로를 생성하고 path traversal을 방지한다."""
    if not re.fullmatch(r"[a-f0-9]{12}", job_id):
        raise ValueError(f"잘못된 job_id 형식: {job_id}")
    job_dir = (OUTPUT_BASE_DIR / job_id).resolve()
    base_resolved = OUTPUT_BASE_DIR.resolve()
    if not job_dir.is_relative_to(base_resolved):
        raise ValueError("잘못된 경로")
    return job_dir


def get_user_job(
    job_id: str,
    current_user: dict,
) -> dict[str, Any]:
    """Job을 조회하고 소유권을 확인한다."""
    store = get_job_store()
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다")
    if job.get("user_id") is not None and job["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다")
    return job
