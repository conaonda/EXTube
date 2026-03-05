"""구조화된 로깅 설정 (structlog 기반)."""

from __future__ import annotations

import logging
import sys
import uuid

import structlog


def generate_request_id() -> str:
    """고유한 request_id를 생성한다."""
    return uuid.uuid4().hex[:16]


def setup_logging(*, json_format: bool = True, log_level: str = "INFO") -> None:
    """structlog + stdlib 로깅을 초기화한다.

    Args:
        json_format: True이면 JSON 출력, False이면 콘솔 출력.
        log_level: 로깅 레벨.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_format:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer(
            ensure_ascii=False
        )
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # uvicorn 로거도 동일 포맷 사용
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.addHandler(handler)
        uv_logger.propagate = False


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """이름이 지정된 structlog 로거를 반환한다."""
    return structlog.get_logger(name)
