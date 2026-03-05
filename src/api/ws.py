"""WebSocket 기반 Job 진행 상태 실시간 알림."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from src.api.db import JobStore

logger = logging.getLogger(__name__)


class JobProgressManager:
    """Job별 WebSocket 연결을 관리하고 진행 상태를 브로드캐스트한다."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
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


async def websocket_job_handler(
    websocket: WebSocket, job_id: str, job_store: JobStore
) -> None:
    """WebSocket 엔드포인트 핸들러."""
    job = job_store.get(job_id)
    if job is None:
        await websocket.close(code=4004, reason="작업을 찾을 수 없습니다")
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
            # 클라이언트로부터 메시지를 대기 (ping/pong 또는 종료 감지)
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await progress_manager.disconnect(job_id, websocket)
