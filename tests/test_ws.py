"""WebSocket Job 진행 상태 실시간 알림 테스트."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from src.api.main import JobStatus, _job_store, app
from src.api.ws import progress_manager

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_jobs():
    """각 테스트 전후로 작업 저장소를 초기화한다."""
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.commit()
    yield
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.commit()


def _insert_job(job_id: str, **fields) -> None:
    defaults = {
        "status": JobStatus.pending,
        "url": "https://youtu.be/dQw4w9WgXcQ",
    }
    defaults.update(fields)
    _job_store.create(job_id, defaults["status"], defaults["url"])
    update_fields = {}
    if defaults["status"] != JobStatus.pending:
        update_fields["status"] = defaults["status"]
    if defaults.get("error"):
        update_fields["error"] = defaults["error"]
    if defaults.get("result"):
        update_fields["result"] = defaults["result"]
    if defaults.get("progress"):
        update_fields["progress"] = defaults["progress"]
    if update_fields:
        _job_store.update(job_id, **update_fields)


class TestWebSocketEndpoint:
    """WebSocket /ws/jobs/{job_id} 테스트."""

    def test_nonexistent_job_closes_with_4004(self):
        """존재하지 않는 작업은 4004 코드로 닫힌다."""
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/jobs/nonexistent") as ws:
                ws.receive_text()

    def test_connect_pending_job_receives_initial_status(self):
        """대기 중인 작업에 연결하면 초기 상태를 수신한다."""
        _insert_job("aabbccddeew1")
        with client.websocket_connect("/ws/jobs/aabbccddeew1") as ws:
            data = json.loads(ws.receive_text())
            assert data["status"] == "pending"
            assert data["progress"] is None

    def test_connect_completed_job_receives_result(self):
        """완료된 작업에 연결하면 결과를 포함한 상태를 수신한다."""
        _insert_job(
            "aabbccddeew2",
            status=JobStatus.completed,
            result={"num_points3d": 100},
        )
        with client.websocket_connect("/ws/jobs/aabbccddeew2") as ws:
            data = json.loads(ws.receive_text())
            assert data["status"] == "completed"
            assert data["result"]["num_points3d"] == 100

    def test_connect_failed_job_receives_error(self):
        """실패한 작업에 연결하면 에러를 포함한 상태를 수신한다."""
        _insert_job(
            "aabbccddeew3",
            status=JobStatus.failed,
            error="COLMAP 실패",
        )
        with client.websocket_connect("/ws/jobs/aabbccddeew3") as ws:
            data = json.loads(ws.receive_text())
            assert data["status"] == "failed"
            assert data["error"] == "COLMAP 실패"

    def test_connect_processing_job_with_progress(self):
        """처리 중인 작업에 연결하면 진행 상태를 수신한다."""
        _insert_job("aabbccddeew4", status=JobStatus.processing)
        _job_store.update(
            "aabbccddeew4",
            progress={"stage": "download", "percent": 50, "message": "다운로드 중"},
        )
        with client.websocket_connect("/ws/jobs/aabbccddeew4") as ws:
            data = json.loads(ws.receive_text())
            assert data["status"] == "processing"
            assert data["progress"]["stage"] == "download"
            assert data["progress"]["percent"] == 50


class TestJobProgressManager:
    """JobProgressManager 단위 테스트."""

    def test_has_connections_initially_false(self):
        """초기 상태에서는 연결이 없다."""
        assert not progress_manager.has_connections("nonexistent")
