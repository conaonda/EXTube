"""Sliding window 인메모리 rate limiting 미들웨어."""

from __future__ import annotations

import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


@dataclass
class RateLimitRule:
    """Rate limit 규칙."""

    max_requests: int
    window_seconds: int


@dataclass
class _SlidingWindow:
    """IP별 sliding window 요청 기록."""

    timestamps: list[float] = field(default_factory=list)

    def count_and_clean(self, now: float, window: float) -> int:
        """윈도우 밖의 타임스탬프를 제거하고 현재 윈도우 내 요청 수를 반환한다."""
        cutoff = now - window
        self.timestamps = [t for t in self.timestamps if t > cutoff]
        return len(self.timestamps)

    def add(self, now: float) -> None:
        self.timestamps.append(now)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """인메모리 sliding window rate limiter."""

    def __init__(
        self,
        app,
        *,
        default_rule: RateLimitRule = RateLimitRule(max_requests=100, window_seconds=60),
        path_rules: dict[tuple[str, str], RateLimitRule] | None = None,
    ):
        super().__init__(app)
        self.default_rule = default_rule
        self.path_rules = path_rules or {}
        self._windows: dict[str, _SlidingWindow] = defaultdict(_SlidingWindow)
        self._lock = threading.Lock()

    def reset(self) -> None:
        """모든 rate limit 상태를 초기화한다. 테스트용."""
        with self._lock:
            self._windows.clear()

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _get_rule(self, method: str, path: str) -> RateLimitRule:
        for (rule_method, rule_path), rule in self.path_rules.items():
            if method.upper() == rule_method.upper() and path == rule_path:
                return rule
        return self.default_rule

    async def dispatch(self, request: Request, call_next):
        method = request.method
        path = request.url.path
        rule = self._get_rule(method, path)
        client_ip = self._get_client_ip(request)

        key = f"{client_ip}:{method}:{path}" if rule is not self.default_rule else f"{client_ip}:default"

        now = time.monotonic()
        with self._lock:
            window = self._windows[key]
            count = window.count_and_clean(now, rule.window_seconds)
            if count >= rule.max_requests:
                retry_after = int(rule.window_seconds - (now - window.timestamps[0])) + 1
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too Many Requests"},
                    headers={"Retry-After": str(max(1, retry_after))},
                )
            window.add(now)

        return await call_next(request)
