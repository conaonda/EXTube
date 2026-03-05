"""pydantic-settings 기반 애플리케이션 설정."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수 / .env 파일로 주입 가능한 설정."""

    model_config = SettingsConfigDict(env_prefix="EXTUBE_", env_file=".env")

    # 작업 관련
    max_workers: int = 4
    gpu_concurrency: int = 1
    job_ttl_seconds: int = 24 * 60 * 60  # 24시간
    sse_timeout_seconds: int = 30 * 60  # 30분
    max_jobs_per_user: int = 2  # 사용자별 동시 실행 제한

    # Redis / RQ
    redis_url: str = "redis://localhost:6379"
    rq_queue_name: str = "gpu"
    rq_job_timeout: int = 3 * 60 * 60  # 3시간

    # 경로
    output_base_dir: Path = Path("data/jobs")
    db_path: Path = Path("data/jobs.db")

    # 재시도 설정
    max_retries: int = 3
    retry_base_delay: int = 10  # 초 (지수 백오프: 10s, 30s, 90s)
    retry_backoff_multiplier: int = 3

    # CORS (쉼표 구분 문자열)
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # 로깅
    log_level: str = "INFO"
    log_json: bool = True

    # JWT 인증
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
