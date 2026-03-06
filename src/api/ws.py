"""WebSocket 기반 Job 진행 상태 실시간 알림."""

from __future__ import annotations

import asyncio
import json
import threading
from collections import defaultdict
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from src.api.config import get_settings
from src.api.db import JobStore
from src.api.logging_config import get_logger

logger = get_logger(__name__)


class JobProgressManager:
    """Job별 WebSocket 연결을 관리하고 진행 상태를 브로드캐스트한다."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections[job_id].append(websocket)
        count = len(self._connections[job_id])
        logger.info("WebSocket 연결: job %s (총 %d)", job_id, count)

    async def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._connections[job_id]
            if websocket in conns:
                conns.remove(websocket)
            if not conns:
                del self._connections[job_id]
        logger.info("WebSocket 해제: job %s", job_id)

    async def broadcast(self, job_id: str, data: dict[str, Any]) -> None:
        """job_id에 연결된 모든 WebSocket 클라이언트에 메시지를 전송한다."""
        async with self._lock:
            conns = list(self._connections.get(job_id, []))
        message = json.dumps(data, ensure_ascii=False)
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    conns_list = self._connections.get(job_id, [])
                    if ws in conns_list:
                        conns_list.remove(ws)

    def has_connections(self, job_id: str) -> bool:
        return bool(self._connections.get(job_id))


progress_manager = JobProgressManager()


def broadcast_progress(job_id: str, data: dict[str, Any]) -> None:
    """동기 코드에서 WebSocket 브로드캐스트를 스케줄링한다."""
    if not progress_manager.has_connections(job_id):
        return
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(
            asyncio.ensure_future, progress_manager.broadcast(job_id, data)
        )
    except RuntimeError:
        pass


_subscriber_thread: threading.Thread | None = None
_subscriber_stop = threading.Event()


def start_redis_subscriber(redis_url: str) -> None:
    """Redis pub/sub 구독 스레드를 시작한다. worker의 진행 상태를 WebSocket으로 중계."""
    global _subscriber_thread  # noqa: PLW0603

    if _subscriber_thread is not None:
        return

    def _run() -> None:
        import redis

        conn = redis.from_url(redis_url)
        pubsub = conn.pubsub()
        pubsub.psubscribe("job:*:progress")
        try:
            while not _subscriber_stop.is_set():
                message = pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    continue
                if message["type"] != "pmessage":
                    continue
                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()
                # channel format: job:{job_id}:progress
                parts = channel.split(":")
                if len(parts) != 3:
                    continue
                job_id = parts[1]
                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue
                broadcast_progress(job_id, data)
        except Exception:
            logger.exception("Redis subscriber 오류")
        finally:
            pubsub.close()
            conn.close()

    _subscriber_thread = threading.Thread(target=_run, daemon=True)
    _subscriber_thread.start()
    logger.info("Redis pub/sub subscriber 시작")


def stop_redis_subscriber() -> None:
    """Redis pub/sub 구독 스레드를 종료한다."""
    global _subscriber_thread  # noqa: PLW0603
    _subscriber_stop.set()
    if _subscriber_thread is not None:
        _subscriber_thread.join(timeout=3)
        _subscriber_thread = None
    _subscriber_stop.clear()


def _authenticate_ws_token(token: str | None) -> dict | None:
    """WebSocket용 JWT 토큰을 검증하고 사용자 정보를 반환한다. 실패 시 None."""
    if not token:
        return None
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        user_id = payload.get("sub")
        if user_id is None or payload.get("type") != "access":
            return None
        return {"id": user_id, "username": payload.get("username")}
    except JWTError:
        return None


_WS_AUTH_TIMEOUT_SECONDS = 5


async def websocket_job_handler(
    websocket: WebSocket, job_id: str, job_store: JobStore
) -> None:
    """WebSocket 엔드포인트 핸들러.

    인증은 첫 번째 메시지로 JWT 토큰을 전달받아 처리한다.
    연결 후 일정 시간 내 인증 메시지가 없으면 연결을 종료한다.
    """
    await websocket.accept()

    # 첫 번째 메시지로 인증 토큰 수신
    try:
        auth_message = await asyncio.wait_for(
            websocket.receive_text(),
            timeout=_WS_AUTH_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        await websocket.close(code=4001, reason="인증 타임아웃")
        return
    except WebSocketDisconnect:
        return

    # 토큰 파싱: 순수 토큰 문자열 또는 JSON {"token": "..."} 지원
    token: str | None = None
    try:
        parsed = json.loads(auth_message)
        if isinstance(parsed, dict):
            token = parsed.get("token")
    except (json.JSONDecodeError, TypeError):
        token = auth_message.strip()

    user = _authenticate_ws_token(token)
    if user is None:
        await websocket.close(code=4001, reason="인증이 필요합니다")
        return

    job = job_store.get(job_id)
    if job is None:
        await websocket.close(code=4004, reason="작업을 찾을 수 없습니다")
        return

    # 소유권 검증
    if job.get("user_id") and job["user_id"] != user["id"]:
        await websocket.close(code=4003, reason="접근 권한이 없습니다")
        return

    await progress_manager.connect(job_id, websocket)

    # 현재 상태를 즉시 전송
    initial = {
        "status": job["status"],
        "progress": job.get("progress"),
    }
    if job["status"] == "completed":
        initial["result"] = job.get("result")
    elif job["status"] == "failed":
        initial["error"] = job.get("error")
    await websocket.send_text(json.dumps(initial, ensure_ascii=False))

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await progress_manager.disconnect(job_id, websocket)
