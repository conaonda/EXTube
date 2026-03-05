"""서버 재시작 시 stale Job 복구 테스트."""

from __future__ import annotations

from src.api.db import JobStore


def test_fail_stale_jobs(tmp_path):
    """pending/processing 상태의 Job이 failed로 전환된다."""
    store = JobStore(db_path=tmp_path / "test.db")
    store.create("aabbccddeef1", "pending", "https://youtu.be/x")
    store.create("aabbccddeef2", "processing", "https://youtu.be/y")
    store.create("aabbccddeef3", "completed", "https://youtu.be/z")

    count = store.fail_stale_jobs(
        statuses=["pending", "processing"],
        error="서버 재시작",
    )
    assert count == 2

    job1 = store.get("aabbccddeef1")
    assert job1["status"] == "failed"
    assert job1["error"] == "서버 재시작"

    job2 = store.get("aabbccddeef2")
    assert job2["status"] == "failed"

    job3 = store.get("aabbccddeef3")
    assert job3["status"] == "completed"

    store.close()


def test_fail_stale_jobs_no_matches(tmp_path):
    """대상 Job이 없으면 0을 반환한다."""
    store = JobStore(db_path=tmp_path / "test.db")
    store.create("aabbccddeef4", "completed", "https://youtu.be/x")

    count = store.fail_stale_jobs(
        statuses=["pending", "processing"],
        error="서버 재시작",
    )
    assert count == 0
    store.close()
