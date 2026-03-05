"""요청/응답 로깅 및 글로벌 에러 핸들링 미들웨어."""

from __future__ import annotations

import time

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from src.api.logging_config import generate_request_id

logger = structlog.get_logger("api.middleware")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """요청/응답을 구조화된 로그로 기록하는 미들웨어.

    각 요청에 고유한 request_id를 부여하고, 응답 헤더에도 포함한다.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = generate_request_id()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        request.state.request_id = request_id

        start = time.monotonic()

        logger.info(
            "request_started",
            method=request.method,
            path=request.url.path,
            client=request.client.host if request.client else None,
        )

        response = await call_next(request)

        duration_ms = round((time.monotonic() - start) * 1000, 2)

        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        response.headers["X-Request-ID"] = request_id
        return response


def register_exception_handlers(app: FastAPI) -> None:
    """글로벌 예외 핸들러를 등록한다."""

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.error(
            "unhandled_exception",
            exc_type=type(exc).__name__,
            exc_message=str(exc),
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "서버 내부 오류가 발생했습니다",
                "request_id": request_id,
            },
        )
