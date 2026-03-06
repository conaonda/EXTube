"""스토리지 엔드포인트."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api import dependencies
from src.api.auth import get_current_user
from src.api.dependencies import get_job_store

router = APIRouter(prefix="/api", tags=["storage"])


class StorageUsageResponse(BaseModel):
    """스토리지 사용량 응답."""

    user_id: str
    total_bytes: int
    total_mb: float
    job_count: int


@router.get(
    "/storage/usage",
    response_model=StorageUsageResponse,
    summary="스토리지 사용량 조회",
)
def get_storage_usage(
    current_user: dict = Depends(get_current_user),
) -> StorageUsageResponse:
    """현재 사용자의 스토리지 사용량을 반환한다."""
    store = get_job_store()
    data = store.get_user_storage_usage(
        current_user["id"], dependencies.get_output_base_dir(),
    )
    return StorageUsageResponse(**data)
