"""스토리지 정리 및 보존 정책 테스트."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from src.api.cleanup import (
    cleanup_expired_results,
    cleanup_intermediate_files,
)
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
def _clear_state():
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
    # 테스트 디렉토리 정리
    import shutil

    for d in OUTPUT_BASE.iterdir():
        if d.is_dir() and len(d.name) == 12:
            shutil.rmtree(d, ignore_errors=True)


def _register_and_login(username="testuser", password="testpass123"):
    client.post("/auth/register", json={"username": username, "password": password})
    resp = client.post("/auth/login", data={"username": username, "password": password})
    return resp.json()


def _auth_header(username="testuser", password="testpass123") -> dict:
    tokens = _register_and_login(username, password)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_old_completed_job(
    user_id: str, job_id: str, age_seconds: float = 8 * 86400
):
    """지정된 시간 전에 완료된 Job을 생성하고 디렉토리 구조를 만든다."""
    created_at = time.time() - age_seconds
    _job_store._conn.execute(
        """INSERT INTO jobs (id, url, status, user_id, created_at)
           VALUES (?, ?, 'completed', ?, ?)""",
        (job_id, "https://www.youtube.com/watch?v=test", user_id, created_at),
    )
    _job_store._conn.commit()

    job_dir = OUTPUT_BASE / job_id
    # 중간 파일들
    dirs = ["reconstruction/dense", "reconstruction/sparse",
            "extraction", "download"]
    for d in dirs:
        (job_dir / d).mkdir(parents=True, exist_ok=True)
        (job_dir / d / "dummy.bin").write_bytes(b"\x00" * 1024)
    # 최종 결과물
    recon = job_dir / "reconstruction"
    (recon / "points.ply").write_bytes(b"ply data")
    (recon / "reconstruction_metadata.json").write_text("{}")
    # 중간 DB 파일
    (recon / "database.db").write_bytes(b"\x00" * 512)

    return job_dir


class TestCleanupIntermediateFiles:
    """중간 파일 정리 테스트."""

    def test_cleans_old_intermediate_files(self):
        _auth_header()
        user = _job_store.users.get_by_username("testuser")
        job_dir = _create_old_completed_job(user["id"], "aabbccddeeff")

        cleaned = cleanup_intermediate_files(_job_store, OUTPUT_BASE, ttl=7 * 86400)

        assert cleaned == 1
        # 중간 파일 삭제됨
        assert not (job_dir / "reconstruction/dense").exists()
        assert not (job_dir / "reconstruction/sparse").exists()
        assert not (job_dir / "extraction").exists()
        assert not (job_dir / "download").exists()
        assert not (job_dir / "reconstruction/database.db").exists()
        # 최종 결과물 유지
        assert (job_dir / "reconstruction/points.ply").exists()
        assert (job_dir / "reconstruction/reconstruction_metadata.json").exists()

    def test_skips_recent_jobs(self):
        _auth_header()
        user = _job_store.users.get_by_username("testuser")
        # 1일 전 생성 — 7일 TTL보다 최근
        _create_old_completed_job(user["id"], "aabbccddeeff", age_seconds=86400)

        cleaned = cleanup_intermediate_files(_job_store, OUTPUT_BASE, ttl=7 * 86400)
        assert cleaned == 0


class TestCleanupExpiredResults:
    """최종 결과물 삭제 테스트."""

    def test_deletes_expired_jobs(self):
        _auth_header()
        user = _job_store.users.get_by_username("testuser")
        # 31일 전 생성
        job_dir = _create_old_completed_job(
            user["id"], "aabbccddeeff", age_seconds=31 * 86400
        )

        deleted = cleanup_expired_results(_job_store, OUTPUT_BASE, ttl=30 * 86400)

        assert deleted == 1
        assert not job_dir.exists()
        assert _job_store.get("aabbccddeeff") is None

    def test_keeps_recent_results(self):
        _auth_header()
        user = _job_store.users.get_by_username("testuser")
        # 15일 전 — 30일 TTL 이내
        _create_old_completed_job(user["id"], "aabbccddeeff", age_seconds=15 * 86400)

        deleted = cleanup_expired_results(_job_store, OUTPUT_BASE, ttl=30 * 86400)
        assert deleted == 0


class TestStorageUsageAPI:
    """GET /api/storage/usage 테스트."""

    def test_returns_usage(self):
        headers = _auth_header()
        user = _job_store.users.get_by_username("testuser")
        _create_old_completed_job(user["id"], "aabbccddeeff", age_seconds=100)

        resp = client.get("/api/storage/usage", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == user["id"]
        assert data["total_bytes"] > 0
        assert data["job_count"] == 1

    def test_no_auth_returns_401(self):
        resp = client.get("/api/storage/usage")
        assert resp.status_code == 401

    def test_empty_usage(self):
        headers = _auth_header()
        resp = client.get("/api/storage/usage", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_bytes"] == 0
        assert data["job_count"] == 0
