"""FastAPI API 테스트."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.api.main import JobStatus, _jobs, app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_jobs():
    """각 테스트 전후로 작업 저장소를 초기화한다."""
    _jobs.clear()
    yield
    _jobs.clear()


class TestCreateJob:
    """POST /api/jobs 테스트."""

    def test_invalid_url_returns_400(self):
        """유효하지 않은 URL은 400을 반환한다."""
        resp = client.post(
            "/api/jobs", json={"url": "not-a-url"}
        )
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
        assert data["url"] == (
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        )
        assert data["id"] in _jobs

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
        _jobs["test123"] = {
            "id": "test123",
            "status": JobStatus.completed,
            "url": "https://youtu.be/dQw4w9WgXcQ",
            "error": None,
            "result": {"num_points3d": 100},
        }
        resp = client.get("/api/jobs/test123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"]["num_points3d"] == 100

    def test_get_failed_job(self):
        """실패한 작업 조회."""
        _jobs["fail123"] = {
            "id": "fail123",
            "status": JobStatus.failed,
            "url": "https://youtu.be/dQw4w9WgXcQ",
            "error": "COLMAP 실패",
            "result": None,
        }
        resp = client.get("/api/jobs/fail123")
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
        _jobs["pending1"] = {
            "id": "pending1",
            "status": JobStatus.processing,
            "url": "https://youtu.be/dQw4w9WgXcQ",
        }
        resp = client.get("/api/jobs/pending1/result")
        assert resp.status_code == 400
        assert "완료되지 않았습니다" in resp.json()["detail"]

    def test_ply_not_found(self):
        """PLY 파일이 없으면 404를 반환한다."""
        _jobs["done1"] = {
            "id": "done1",
            "status": JobStatus.completed,
            "url": "https://youtu.be/dQw4w9WgXcQ",
        }
        resp = client.get("/api/jobs/done1/result")
        assert resp.status_code == 404

    def test_download_ply(self, tmp_path):
        """PLY 파일을 다운로드한다."""
        ply_file = tmp_path / "points.ply"
        ply_file.write_text("ply content")

        _jobs["done2"] = {
            "id": "done2",
            "status": JobStatus.completed,
            "url": "https://youtu.be/dQw4w9WgXcQ",
            "ply_path": str(ply_file),
        }
        resp = client.get("/api/jobs/done2/result")
        assert resp.status_code == 200
        assert resp.content == b"ply content"
