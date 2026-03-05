"""요청/응답 로깅 및 글로벌 에러 핸들링 미들웨어."""

from __future__ import annotations

import time

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.api.logging_config import generate_request_id

logger = structlog.get_logger("api.middleware")


class SecurityHeadersMiddleware:
    """OWASP 권장 보안 헤더를 응답에 추가하는 ASGI 미들웨어."""

    # 기본 보안 헤더 (환경 무관)
    _BASE_HEADERS: list[tuple[bytes, bytes]] = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"x-xss-protection", b"0"),
        (b"referrer-policy", b"strict-origin-when-cross-origin"),
        (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    ]

    # 프로덕션 전용 헤더
    _PROD_HEADERS: list[tuple[bytes, bytes]] = [
        (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
        (
            b"content-security-policy",
            b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';"
            b" img-src 'self' data: blob:; connect-src 'self'; font-src 'self';"
            b" object-src 'none'; frame-ancestors 'none'; base-uri 'self'",
        ),
    ]

    def __init__(self, app: ASGIApp, environment: str = "development") -> None:
        self.app = app
        self._headers = list(self._BASE_HEADERS)
        if environment == "production":
            self._headers.extend(self._PROD_HEADERS)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        security_headers = self._headers

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # 서버 정보 헤더 제거
                headers = [(k, v) for k, v in headers if k.lower() != b"server"]
                headers.extend(security_headers)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RequestLoggingMiddleware:
    """요청/응답을 구조화된 로그로 기록하는 순수 ASGI 미들웨어.

    BaseHTTPMiddleware 대신 ASGI 프로토콜을 직접 구현하여
    SSE 스트리밍 응답과의 호환성을 보장한다.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = generate_request_id()
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        scope["state"] = {**scope.get("state", {}), "request_id": request_id}

        method = scope.get("method", "")
        # ASGI scope["path"]는 query string을 포함하지 않으므로
        # URL 토큰(?token=...)이 로그에 노출되지 않는다.
        path = scope.get("path", "")
        client = scope.get("client")
        client_host = client[0] if client else None

        start = time.monotonic()

        logger.info(
            "request_started",
            method=method,
            path=path,
            client=client_host,
        )

        status_code: int | None = None

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status")
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)

        duration_ms = round((time.monotonic() - start) * 1000, 2)

        logger.info(
            "request_completed",
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
        )


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
