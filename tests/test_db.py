"""JobStore (SQLite) 테스트."""

from __future__ import annotations

import time

import pytest
from src.api.db import JobStore


@pytest.fixture()
def store(tmp_path):
    """임시 DB로 JobStore를 생성한다."""
    s = JobStore(tmp_path / "test.db")
    yield s
    s.close()


class TestJobStore:
    def test_create_and_get(self, store):
        store.create("abc123def456", "pending", "https://youtu.be/abc")
        job = store.get("abc123def456")
        assert job is not None
        assert job["id"] == "abc123def456"
        assert job["status"] == "pending"
        assert job["url"] == "https://youtu.be/abc"

    def test_get_nonexistent(self, store):
        assert store.get("nonexistent") is None

    def test_update(self, store):
        store.create("abc123def456", "pending", "https://youtu.be/abc")
        store.update("abc123def456", status="completed", result={"pts": 42})
        job = store.get("abc123def456")
        assert job["status"] == "completed"
        assert job["result"] == {"pts": 42}

    def test_update_error(self, store):
        store.create("abc123def456", "pending", "https://youtu.be/abc")
        store.update("abc123def456", status="failed", error="boom")
        job = store.get("abc123def456")
        assert job["error"] == "boom"

    def test_cleanup_expired(self, store, tmp_path):
        store.create("abc123def456", "completed", "https://youtu.be/abc")
        # Manually set created_at to the past
        store._conn.execute(
            "UPDATE jobs SET created_at = ? WHERE id = ?",
            (time.time() - 100000, "abc123def456"),
        )
        store._conn.commit()

        jobs_dir = tmp_path / "jobs"
        job_dir = jobs_dir / "abc123def456"
        job_dir.mkdir(parents=True)
        (job_dir / "data.txt").write_text("test")

        deleted = store.cleanup_expired(jobs_dir, ttl=1)
        assert deleted == 1
        assert store.get("abc123def456") is None
        assert not job_dir.exists()

    def test_cleanup_keeps_recent(self, store, tmp_path):
        store.create("abc123def456", "pending", "https://youtu.be/abc")
        deleted = store.cleanup_expired(tmp_path, ttl=86400)
        assert deleted == 0
        assert store.get("abc123def456") is not None
