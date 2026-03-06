"""FastAPI 애플리케이션 — 라우터 등록 및 미들웨어 구성."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from src.api.auth import router as auth_router
from src.api.auth import set_job_store
from src.api.config import get_settings
from src.api.db import JobStore
from src.api.dependencies import init_job_store
from src.api.middleware import (
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    register_exception_handlers,
)
from src.api.rate_limit import RateLimitMiddleware, RateLimitRule
from src.api.routers.files import router as files_router
from src.api.routers.health import router as health_router
from src.api.routers.jobs import (  # noqa: F401
    JobCreate,
    JobResponse,
    JobStatus,
)
from src.api.routers.jobs import (
    router as jobs_router,
)
from src.api.routers.storage import router as storage_router
from src.api.ws import (
    start_redis_subscriber,
    stop_redis_subscriber,
    websocket_job_handler,
)

logger = logging.getLogger(__name__)

_settings = get_settings()

# Job 저장소 (SQLite)
_job_store = JobStore(db_path=_settings.db_path)
set_job_store(_job_store)
init_job_store(_job_store)


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    """서버 시작 시 만료된 Job 정리 및 stale Job 복구."""
    deleted = _job_store.cleanup_expired(
        _settings.output_base_dir, ttl=_settings.job_ttl_seconds
    )
    if deleted:
        logger.info("만료된 Job %d개 정리됨", deleted)

    recovered = _job_store.fail_stale_jobs(
        statuses=["pending", "processing", "retrying"],
        error="서버 재시작으로 인해 작업이 중단되었습니다. 재제출해 주세요.",
    )
    if recovered:
        logger.info("재시작 복구: %d개 Job을 failed로 전환", recovered)

    start_redis_subscriber(_settings.redis_url)
    yield
    stop_redis_subscriber()


_docs_url = None if _settings.environment == "production" else "/docs"
_redoc_url = None if _settings.environment == "production" else "/redoc"

app = FastAPI(
    title="EXTube API",
    version="0.5.0",
    description=(
        "유튜브 영상에서 사진측량(photogrammetry) 기술을 활용해 "
        "3차원 공간을 복원하는 API 서비스."
    ),
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    lifespan=_lifespan,
)

# --- 라우터 등록 ---
app.include_router(auth_router)
app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(files_router)
app.include_router(storage_router)

# --- 미들웨어 ---
app.add_middleware(
    SecurityHeadersMiddleware, environment=_settings.environment,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID"],
)

app.add_middleware(
    RateLimitMiddleware,
    default_rule=RateLimitRule(max_requests=100, window_seconds=60),
    path_rules={
        ("POST", "/api/jobs"): RateLimitRule(
            max_requests=5, window_seconds=3600,
        ),
    },
)

app.add_middleware(RequestLoggingMiddleware)

# 글로벌 예외 핸들러
register_exception_handlers(app)

# Prometheus 메트릭
_instrumentator = Instrumentator(
    excluded_handlers=["/metrics", "/health", "/health/ready"],
).instrument(app)


# WebSocket
@app.websocket("/ws/jobs/{job_id}")
async def ws_job_progress(websocket: WebSocket, job_id: str) -> None:
    """WebSocket으로 작업 진행률을 실시간 전달한다."""
    await websocket_job_handler(websocket, job_id, _job_store)


# 정적 파일 서빙
STATIC_DIR = Path(__file__).resolve().parent.parent / "viewer" / "dist"
OUTPUT_BASE_DIR = _settings.output_base_dir


def mount_static_files() -> None:
    """프론트엔드 빌드 결과물을 정적 파일로 서빙한다."""
    if STATIC_DIR.is_dir():
        app.mount(
            "/",
            StaticFiles(directory=str(STATIC_DIR), html=True),
            name="static",
        )


mount_static_files()
