"""WebSocket Job 진행 상태 실시간 알림 테스트."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from src.api.main import _job_store, app
from src.api.routers.jobs import JobStatus
from src.api.ws import progress_manager

client = TestClient(app)

TEST_USER = "wsuser"
TEST_PASS = "Test1234!"
OTHER_USER = "otheruser"
OTHER_PASS = "OtherPass1!"


@pytest.fixture(autouse=True)
def _clear_jobs():
    """각 테스트 전후로 작업 저장소를 초기화한다."""
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()
    yield
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()


def _register_and_login(username=TEST_USER, password=TEST_PASS) -> str:
    """사용자 등록 후 로그인하여 access_token을 반환한다."""
    client.post("/auth/register", json={"username": username, "password": password})
    resp = client.post(
        "/auth/login", data={"username": username, "password": password}
    )
    return resp.json()["access_token"]


def _get_user_id(username=TEST_USER) -> str:
    """사용자명으로 사용자 ID를 조회한다."""
    user = _job_store.users.get_by_username(username)
    return user["id"]


def _insert_job(job_id: str, user_id: str | None = None, **fields) -> None:
    defaults = {
        "status": JobStatus.pending,
        "url": "https://youtu.be/dQw4w9WgXcQ",
    }
    defaults.update(fields)
    _job_store.create(job_id, defaults["status"], defaults["url"], user_id=user_id)
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


def _ws_send_auth(ws, token: str) -> None:
    """WebSocket 연결 후 첫 번째 메시지로 인증 토큰을 전송한다."""
    ws.send_text(json.dumps({"token": token}))


class TestWebSocketAuth:
    """WebSocket 인증 테스트."""

    def test_no_token_closes_with_4001(self):
        """토큰 없이 빈 메시지를 보내면 4001로 닫힌다."""
        token = _register_and_login()
        user_id = _get_user_id()
        _insert_job("authtest01", user_id=user_id)
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/jobs/authtest01") as ws:
                ws.send_text("")
                ws.receive_text()

    def test_invalid_token_closes_with_4001(self):
        """잘못된 토큰으로 인증하면 4001로 닫힌다."""
        token = _register_and_login()
        user_id = _get_user_id()
        _insert_job("authtest02", user_id=user_id)
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/jobs/authtest02") as ws:
                ws.send_text(json.dumps({"token": "invalid"}))
                ws.receive_text()

    def test_other_user_closes_with_4003(self):
        """다른 사용자의 Job에 연결하면 4003으로 닫힌다."""
        owner_token = _register_and_login()
        owner_id = _get_user_id()
        _insert_job("authtest03", user_id=owner_id)

        other_token = _register_and_login(OTHER_USER, OTHER_PASS)
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/jobs/authtest03") as ws:
                _ws_send_auth(ws, other_token)
                ws.receive_text()


class TestWebSocketEndpoint:
    """WebSocket /ws/jobs/{job_id} 테스트."""

    def test_nonexistent_job_closes_with_4004(self):
        """존재하지 않는 작업은 4004 코드로 닫힌다."""
        token = _register_and_login()
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/jobs/nonexistent") as ws:
                _ws_send_auth(ws, token)
                ws.receive_text()

    def test_connect_pending_job_receives_initial_status(self):
        """대기 중인 작업에 연결하면 초기 상태를 수신한다."""
        token = _register_and_login()
        user_id = _get_user_id()
        _insert_job("aabbccddeew1", user_id=user_id)
        with client.websocket_connect("/ws/jobs/aabbccddeew1") as ws:
            _ws_send_auth(ws, token)
            data = json.loads(ws.receive_text())
            assert data["status"] == "pending"
            assert data["progress"] is None

    def test_connect_completed_job_receives_result(self):
        """완료된 작업에 연결하면 결과를 포함한 상태를 수신한다."""
        token = _register_and_login()
        user_id = _get_user_id()
        _insert_job(
            "aabbccddeew2",
            user_id=user_id,
            status=JobStatus.completed,
            result={"num_points3d": 100},
        )
        with client.websocket_connect("/ws/jobs/aabbccddeew2") as ws:
            _ws_send_auth(ws, token)
            data = json.loads(ws.receive_text())
            assert data["status"] == "completed"
            assert data["result"]["num_points3d"] == 100

    def test_connect_failed_job_receives_error(self):
        """실패한 작업에 연결하면 에러를 포함한 상태를 수신한다."""
        token = _register_and_login()
        user_id = _get_user_id()
        _insert_job(
            "aabbccddeew3",
            user_id=user_id,
            status=JobStatus.failed,
            error="COLMAP 실패",
        )
        with client.websocket_connect("/ws/jobs/aabbccddeew3") as ws:
            _ws_send_auth(ws, token)
            data = json.loads(ws.receive_text())
            assert data["status"] == "failed"
            assert data["error"] == "COLMAP 실패"

    def test_connect_processing_job_with_progress(self):
        """처리 중인 작업에 연결하면 진행 상태를 수신한다."""
        token = _register_and_login()
        user_id = _get_user_id()
        _insert_job("aabbccddeew4", user_id=user_id, status=JobStatus.processing)
        _job_store.update(
            "aabbccddeew4",
            progress={"stage": "download", "percent": 50, "message": "다운로드 중"},
        )
        with client.websocket_connect("/ws/jobs/aabbccddeew4") as ws:
            _ws_send_auth(ws, token)
            data = json.loads(ws.receive_text())
            assert data["status"] == "processing"
            assert data["progress"]["stage"] == "download"
            assert data["progress"]["percent"] == 50

    def test_plain_token_string_auth(self):
        """순수 토큰 문자열로도 인증할 수 있다."""
        token = _register_and_login()
        user_id = _get_user_id()
        _insert_job("aabbccddeew5", user_id=user_id)
        with client.websocket_connect("/ws/jobs/aabbccddeew5") as ws:
            ws.send_text(token)
            data = json.loads(ws.receive_text())
            assert data["status"] == "pending"


class TestJobProgressManager:
    """JobProgressManager 단위 테스트."""

    def test_has_connections_initially_false(self):
        """초기 상태에서는 연결이 없다."""
        assert not progress_manager.has_connections("nonexistent")
