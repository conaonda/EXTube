"""3D 결과물 정적 파일 서빙 API 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from src.api.config import get_settings
from src.api.main import _job_store, app
from src.api.rate_limit import RateLimitMiddleware

client = TestClient(app)
settings = get_settings()
OUTPUT_BASE = Path(settings.output_base_dir).resolve()


def _reset_rate_limiter():
    stack = app.middleware_stack
    while stack is not None:
        if isinstance(stack, RateLimitMiddleware):
            stack.reset()
            return
        stack = getattr(stack, "app", None)


@pytest.fixture(autouse=True)
def _clear_db(tmp_path):
    """각 테스트 전후로 DB 및 테스트 파일을 초기화한다."""
    _reset_rate_limiter()
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()
    yield
    _job_store._conn.execute("DELETE FROM jobs")
    _job_store._conn.execute("DELETE FROM users")
    _job_store._conn.execute("DELETE FROM refresh_tokens")
    _job_store._conn.commit()


def _register_and_login(username="testuser", password="Test1234!"):
    client.post("/auth/register", json={"username": username, "password": password})
    resp = client.post("/auth/login", data={"username": username, "password": password})
    return resp.json()


def _auth_header(username="testuser", password="Test1234!") -> dict:
    tokens = _register_and_login(username, password)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _get_token(username="testuser", password="Test1234!") -> str:
    tokens = _register_and_login(username, password)
    return tokens["access_token"]


def _create_completed_job(user_id: str, job_id: str = "aabbccddeeff"):
    """완료된 Job을 DB에 직접 생성한다."""
    _job_store._conn.execute(
        """INSERT INTO jobs (id, url, status, user_id, created_at)
           VALUES (?, ?, 'completed', ?, strftime('%s', 'now'))""",
        (job_id, "https://www.youtube.com/watch?v=test", user_id),
    )
    _job_store._conn.commit()
    return job_id


def _create_job_with_ply(user_id: str, job_id: str = "aabbccddeeff"):
    """PLY 파일이 있는 완료된 Job을 생성한다."""
    job_dir = OUTPUT_BASE / job_id / "reconstruction"
    job_dir.mkdir(parents=True, exist_ok=True)
    ply_path = job_dir / "points.ply"
    ply_path.write_bytes(b"ply\nformat ascii 1.0\nend_header\n")

    _job_store._conn.execute(
        """INSERT INTO jobs (id, url, status, user_id, ply_path, created_at)
           VALUES (?, ?, 'completed', ?, ?, strftime('%s', 'now'))""",
        (job_id, "https://www.youtube.com/watch?v=test", user_id, str(ply_path)),
    )
    _job_store._conn.commit()
    return job_id, ply_path


def _create_job_with_splat(user_id: str, job_id: str = "aabbccddeeff"):
    """Splat 파일이 있는 완료된 Job을 생성한다."""
    job_dir = OUTPUT_BASE / job_id / "reconstruction" / "gaussian_splatting"
    job_dir.mkdir(parents=True, exist_ok=True)
    splat_path = job_dir / "output.splat"
    splat_path.write_bytes(b"\x00" * 64)

    _job_store._conn.execute(
        """INSERT INTO jobs (id, url, status, user_id, gs_splat_path, created_at)
           VALUES (?, ?, 'completed', ?, ?, strftime('%s', 'now'))""",
        (job_id, "https://www.youtube.com/watch?v=test", user_id, str(splat_path)),
    )
    _job_store._conn.commit()
    return job_id, splat_path


@pytest.fixture(autouse=True)
def _cleanup_job_dirs():
    yield
    import shutil

    if not OUTPUT_BASE.exists():
        return
    for d in OUTPUT_BASE.iterdir():
        if d.is_dir() and len(d.name) == 12:
            shutil.rmtree(d, ignore_errors=True)


class TestResultEndpointAuth:
    """GET /api/jobs/{job_id}/result 인증 테스트."""

    def test_no_auth_returns_401(self):
        resp = client.get("/api/jobs/aabbccddeeff/result")
        assert resp.status_code == 401

    def test_header_auth_works(self):
        headers = _auth_header()
        user = _job_store.users.get_by_username("testuser")
        job_id, _ = _create_job_with_ply(user["id"])
        resp = client.get(f"/api/jobs/{job_id}/result", headers=headers)
        assert resp.status_code == 200

    def test_query_token_auth_works(self):
        token = _get_token()
        user = _job_store.users.get_by_username("testuser")
        job_id, _ = _create_job_with_ply(user["id"])
        resp = client.get(f"/api/jobs/{job_id}/result?token={token}")
        assert resp.status_code == 200

    def test_invalid_query_token_returns_401(self):
        _auth_header("user_a", "Password1!")
        user = _job_store.users.get_by_username("user_a")
        job_id, _ = _create_job_with_ply(user["id"])
        resp = client.get(f"/api/jobs/{job_id}/result?token=invalid.token.here")
        assert resp.status_code == 401


class TestSplatEndpoint:
    """GET /api/jobs/{job_id}/splat 테스트."""

    def test_splat_with_query_token(self):
        token = _get_token()
        user = _job_store.users.get_by_username("testuser")
        job_id, _ = _create_job_with_splat(user["id"])
        resp = client.get(f"/api/jobs/{job_id}/splat?token={token}")
        assert resp.status_code == 200

    def test_splat_other_user_forbidden(self):
        _auth_header("user_a", "Password1!")
        token_b = _get_token("user_b", "Password2!")
        user_a = _job_store.users.get_by_username("user_a")
        job_id, _ = _create_job_with_splat(user_a["id"])
        resp = client.get(f"/api/jobs/{job_id}/splat?token={token_b}")
        assert resp.status_code == 403


class TestPotreeEndpoint:
    """GET /api/jobs/{job_id}/potree/{file_path} 테스트."""

    def test_potree_with_query_token(self):
        token = _get_token()
        user = _job_store.users.get_by_username("testuser")
        job_id = "aabbccddeeff"

        potree_dir = OUTPUT_BASE / job_id / "reconstruction" / "potree"
        potree_dir.mkdir(parents=True, exist_ok=True)
        metadata = potree_dir / "metadata.json"
        metadata.write_text('{"version": "2.0"}')

        _job_store._conn.execute(
            """INSERT INTO jobs (id, url, status, user_id, potree_dir, created_at)
               VALUES (?, ?, 'completed', ?, ?, strftime('%s', 'now'))""",
            (
                job_id,
                "https://www.youtube.com/watch?v=test",
                user["id"],
                str(potree_dir),
            ),
        )
        _job_store._conn.commit()

        resp = client.get(f"/api/jobs/{job_id}/potree/metadata.json?token={token}")
        assert resp.status_code == 200
        assert resp.json() == {"version": "2.0"}


class TestDownloadEndpoint:
    """GET /api/jobs/{job_id}/download/{file_path} 테스트."""

    def test_download_with_query_token(self):
        token = _get_token()
        user = _job_store.users.get_by_username("testuser")
        job_id = "aabbccddeeff"

        recon_dir = OUTPUT_BASE / job_id / "reconstruction"
        recon_dir.mkdir(parents=True, exist_ok=True)
        test_file = recon_dir / "test_output.ply"
        test_file.write_bytes(b"test data")

        _create_completed_job(user["id"], job_id)

        resp = client.get(f"/api/jobs/{job_id}/download/test_output.ply?token={token}")
        assert resp.status_code == 200
        assert resp.content == b"test data"

    def test_path_traversal_blocked(self):
        token = _get_token()
        user = _job_store.users.get_by_username("testuser")
        job_id = "aabbccddeeff"
        _create_completed_job(user["id"], job_id)

        recon_dir = OUTPUT_BASE / job_id / "reconstruction"
        recon_dir.mkdir(parents=True, exist_ok=True)

        resp = client.get(f"/api/jobs/{job_id}/download/../../etc/passwd?token={token}")
        assert resp.status_code in (400, 404)
