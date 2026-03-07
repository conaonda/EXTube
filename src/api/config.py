"""pydantic-settings 기반 애플리케이션 설정."""

from __future__ import annotations

import logging
import warnings
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    """환경변수 / .env 파일로 주입 가능한 설정."""

    model_config = SettingsConfigDict(env_prefix="EXTUBE_", env_file=".env")

    # 작업 관련
    max_workers: int = 4
    gpu_concurrency: int = 1
    job_ttl_seconds: int = 24 * 60 * 60  # 24시간
    sse_timeout_seconds: int = 30 * 60  # 30분
    max_jobs_per_user: int = 2  # 사용자별 동시 실행 제한
    max_video_duration_seconds: int = 600  # 최대 영상 길이 (기본 10분)
    max_video_filesize_mb: int = 500  # 최대 예상 파일 크기 (MB)

    # Redis / RQ
    redis_url: str = "redis://localhost:6379"
    rq_queue_name: str = "gpu"
    rq_job_timeout: int = 3 * 60 * 60  # 3시간

    # 작업 큐 동시실행 제한
    queue_max_concurrent: int = 1  # 동시 실행 작업 수 제한

    # 경로
    output_base_dir: Path = Path("data/jobs")
    db_path: Path = Path("data/jobs.db")

    # 스토리지 정리 정책
    intermediate_ttl_seconds: int = 7 * 24 * 60 * 60  # 중간 파일 7일
    result_ttl_seconds: int = 30 * 24 * 60 * 60  # 최종 결과물 30일
    cleanup_interval_seconds: int = 6 * 60 * 60  # 정리 주기 6시간

    # 재시도 설정
    max_retries: int = 3
    retry_base_delay: int = 10  # 초 (지수 백오프: 10s, 30s, 90s)
    retry_backoff_multiplier: int = 3

    # 환경 설정
    environment: str = "development"  # development | production

    # CORS (쉼표 구분 문자열)
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # 로깅
    log_level: str = "INFO"
    log_json: bool = True

    # JWT 인증
    jwt_secret_key: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # 로그인 실패 제한
    max_login_attempts: int = 5
    login_lockout_seconds: int = 900  # 15분

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def validate_production_settings(self) -> None:
        """프로덕션 환경에서 필수 보안 설정을 검증한다."""
        if self.jwt_secret_key == _DEFAULT_JWT_SECRET:
            if self.environment == "production":
                raise RuntimeError(
                    "프로덕션 환경에서 JWT 기본키를 사용할 수 없습니다. "
                    "EXTUBE_JWT_SECRET_KEY 환경변수를 설정하세요."
                )
            warnings.warn(
                "JWT 기본키가 사용 중입니다. "
                "프로덕션 배포 전 "
                "EXTUBE_JWT_SECRET_KEY를 변경하세요.",
                UserWarning,
                stacklevel=2,
            )

        if self.environment == "production" and "*" in self.cors_origins:
            raise RuntimeError(
                "프로덕션 환경에서 CORS 와일드카드(*)를 사용할 수 없습니다. "
                "EXTUBE_CORS_ORIGINS 환경변수를 설정하세요."
            )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production_settings()
    return settings
