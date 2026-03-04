"""FastAPI API 테스트."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.api.main import JobStatus, _job_store, app

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
    """테스트용 Job을 DB에 직접 삽입한다."""
    defaults = {
        "status": JobStatus.pending,
        "url": "https://youtu.be/dQw4w9WgXcQ",
        "error": None,
        "result": None,
    }
    defaults.update(fields)
    _job_store.create(job_id, defaults["status"], defaults["url"])
    update_fields = {}
    if defaults["error"] is not None:
        update_fields["error"] = defaults["error"]
    if defaults["result"] is not None:
        update_fields["result"] = defaults["result"]
    if defaults.get("ply_path") is not None:
        update_fields["ply_path"] = defaults["ply_path"]
    # Update status if not pending (create always sets the given status, so we
    # only need to update if extra fields exist)
    if defaults["status"] != JobStatus.pending:
        update_fields["status"] = defaults["status"]
    if update_fields:
        _job_store.update(job_id, **update_fields)


class TestCreateJob:
    """POST /api/jobs 테스트."""

    def test_invalid_url_returns_400(self):
        """유효하지 않은 URL은 400을 반환한다."""
        resp = client.post("/api/jobs", json={"url": "not-a-url"})
        assert resp.status_code == 400
        assert "유효하지 않은" in resp.json()["detail"]

    @patch("src.api.main._run_pipeline")
    def test_valid_url_creates_job(self, mock_run):
        """유효한 URL로 작업을 생성한다."""
        resp = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["url"] == ("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert _job_store.get(data["id"]) is not None

    @patch("src.api.main._run_pipeline")
    def test_custom_params(self, mock_run):
        """커스텀 파라미터가 전달된다."""
        resp = client.post(
            "/api/jobs",
            json={
                "url": "https://youtu.be/dQw4w9WgXcQ",
                "max_height": 720,
                "frame_interval": 2.0,
            },
        )
        assert resp.status_code == 201

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        job_id = call_args[0][0]
        params = call_args[0][1]
        assert _job_store.get(job_id) is not None
        assert params.url == "https://youtu.be/dQw4w9WgXcQ"
        assert params.max_height == 720
        assert params.frame_interval == 2.0
        assert params.blur_threshold == 100.0
        assert params.camera_model == "SIMPLE_RADIAL"

    def test_xss_url_sanitized(self):
        """XSS가 포함된 URL은 sanitize된다."""
        resp = client.post(
            "/api/jobs",
            json={"url": "<script>alert('xss')</script>"},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "<script>" not in detail
        assert "'" not in detail


class TestGetJob:
    """GET /api/jobs/{id} 테스트."""

    def test_not_found(self):
        """존재하지 않는 작업은 404를 반환한다."""
        resp = client.get("/api/jobs/nonexistent")
        assert resp.status_code == 404

    @patch("src.api.main._run_pipeline")
    def test_get_pending_job(self, mock_run):
        """생성된 작업의 상태를 조회한다."""
        create_resp = client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        )
        job_id = create_resp.json()["id"]

        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    def test_get_completed_job(self):
        """완료된 작업 조회."""
        _insert_job(
            "aabbccddeeff",
            status=JobStatus.completed,
            result={"num_points3d": 100},
        )
        resp = client.get("/api/jobs/aabbccddeeff")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"]["num_points3d"] == 100

    def test_get_failed_job(self):
        """실패한 작업 조회."""
        _insert_job(
            "aabbccddeef1",
            status=JobStatus.failed,
            error="COLMAP 실패",
        )
        resp = client.get("/api/jobs/aabbccddeef1")
        assert resp.status_code == 200
        assert resp.json()["error"] == "COLMAP 실패"


class TestGetJobResult:
    """GET /api/jobs/{id}/result 테스트."""

    def test_not_found(self):
        """존재하지 않는 작업은 404를 반환한다."""
        resp = client.get("/api/jobs/nonexistent/result")
        assert resp.status_code == 404

    def test_not_completed(self):
        """완료되지 않은 작업은 400을 반환한다."""
        _insert_job("aabbccddeef2", status=JobStatus.processing)
        resp = client.get("/api/jobs/aabbccddeef2/result")
        assert resp.status_code == 400
        assert "완료되지 않았습니다" in resp.json()["detail"]

    def test_ply_not_found(self):
        """PLY 파일이 없으면 404를 반환한다."""
        _insert_job("aabbccddeef3", status=JobStatus.completed)
        resp = client.get("/api/jobs/aabbccddeef3/result")
        assert resp.status_code == 404

    @patch("src.api.main.OUTPUT_BASE_DIR")
    def test_download_ply(self, mock_base_dir, tmp_path):
        """PLY 파일을 다운로드한다."""
        mock_base_dir.resolve.return_value = tmp_path.resolve()
        ply_file = tmp_path / "points.ply"
        ply_file.write_text("ply content")

        _insert_job(
            "aabbccddeef4",
            status=JobStatus.completed,
            ply_path=str(ply_file),
        )
        resp = client.get("/api/jobs/aabbccddeef4/result")
        assert resp.status_code == 200
        assert resp.content == b"ply content"


class TestStreamJob:
    """GET /api/jobs/{id}/stream 테스트."""

    def test_stream_not_found(self):
        """존재하지 않는 작업은 404를 반환한다."""
        resp = client.get("/api/jobs/nonexistent/stream")
        assert resp.status_code == 404

    def test_stream_completed_job(self):
        """완료된 작업은 즉시 완료 이벤트를 전송한다."""
        _insert_job(
            "aabbccddeef5",
            status=JobStatus.completed,
            result={"num_points3d": 50},
        )
        with client.stream("GET", "/api/jobs/aabbccddeef5/stream") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            lines = []
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    lines.append(json.loads(line[6:]))
            # Should have at least the final event with completed status
            assert any(e["status"] == "completed" for e in lines)

    def test_stream_failed_job(self):
        """실패한 작업은 에러 이벤트를 전송한다."""
        _insert_job(
            "aabbccddeef6",
            status=JobStatus.failed,
            error="테스트 에러",
        )
        with client.stream("GET", "/api/jobs/aabbccddeef6/stream") as resp:
            assert resp.status_code == 200
            lines = []
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    lines.append(json.loads(line[6:]))
            assert any(
                e["status"] == "failed" and e.get("error") == "테스트 에러"
                for e in lines
            )

    def test_stream_with_progress(self):
        """진행률 업데이트가 스트리밍된다."""
        _insert_job("aabbccddeef7", status=JobStatus.processing)
        _job_store.update(
            "aabbccddeef7",
            progress={"stage": "download", "percent": 50, "message": "다운로드 중"},
        )
        # Complete the job so stream terminates
        _job_store.update("aabbccddeef7", status=JobStatus.completed)
        with client.stream("GET", "/api/jobs/aabbccddeef7/stream") as resp:
            assert resp.status_code == 200
            lines = []
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    lines.append(json.loads(line[6:]))
            assert len(lines) >= 1
