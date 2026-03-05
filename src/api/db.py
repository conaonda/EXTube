"""SQLite 기반 Job 저장소."""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_DEFAULT_DB_PATH = Path("data/jobs.db")
_JOB_TTL_SECONDS = 24 * 60 * 60  # 24시간
_ALLOWED_UPDATE_FIELDS = {
    "status",
    "error",
    "result",
    "ply_path",
    "dense_ply_path",
    "gs_splat_path",
    "potree_dir",
    "progress",
}


class JobStore:
    """SQLite 기반 Job CRUD 저장소."""

    def __init__(self, db_path: Path | str = _DEFAULT_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                url TEXT NOT NULL,
                error TEXT,
                result TEXT,
                ply_path TEXT,
                dense_ply_path TEXT,
                gs_splat_path TEXT,
                potree_dir TEXT,
                progress TEXT,
                created_at REAL NOT NULL
            )
        """)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """기존 테이블에 누락된 컬럼을 추가한다."""
        rows = self._conn.execute("PRAGMA table_info(jobs)").fetchall()
        columns = {row[1] for row in rows}
        for col in ("progress", "dense_ply_path", "gs_splat_path", "potree_dir"):
            if col not in columns:
                self._conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
        self._conn.commit()

    def create(self, job_id: str, status: str, url: str) -> dict[str, Any]:
        job = {
            "id": job_id,
            "status": status,
            "url": url,
            "error": None,
            "result": None,
            "ply_path": None,
            "dense_ply_path": None,
            "gs_splat_path": None,
            "potree_dir": None,
            "progress": None,
            "created_at": time.time(),
        }
        sql = (
            "INSERT INTO jobs"
            " (id, status, url, error, result, ply_path,"
            " dense_ply_path, gs_splat_path, potree_dir,"
            " progress, created_at)"
            " VALUES (:id, :status, :url, :error, :result,"
            " :ply_path, :dense_ply_path, :gs_splat_path,"
            " :potree_dir, :progress, :created_at)"
        )
        with self._lock:
            self._conn.execute(sql, job)
            self._conn.commit()
        return self._row_to_dict(job)

    def list(
        self,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Job 목록을 조회한다. 최신순 정렬, 페이지네이션 지원."""
        params: list[Any] = []
        where = ""
        if status is not None:
            where = " WHERE status = ?"
            params.append(status)

        with self._lock:
            count_row = self._conn.execute(
                f"SELECT COUNT(*) FROM jobs{where}", params  # noqa: S608
            ).fetchone()
            total = count_row[0]

            query_params = params + [limit, offset]
            rows = self._conn.execute(
                f"SELECT * FROM jobs{where} ORDER BY created_at DESC LIMIT ? OFFSET ?",  # noqa: S608
                query_params,
            ).fetchall()

        jobs = [self._row_to_dict(dict(row)) for row in rows]
        return {"items": jobs, "total": total}

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(dict(row))

    def update(self, job_id: str, **fields: Any) -> None:
        if invalid := set(fields) - _ALLOWED_UPDATE_FIELDS:
            raise ValueError(f"Invalid fields: {invalid}")
        if "result" in fields and fields["result"] is not None:
            fields["result"] = json.dumps(fields["result"])
        if "progress" in fields and fields["progress"] is not None:
            fields["progress"] = json.dumps(fields["progress"])
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [job_id]
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", vals)  # noqa: S608
            self._conn.commit()

    def cleanup_expired(self, jobs_dir: Path, ttl: float = _JOB_TTL_SECONDS) -> int:
        """TTL이 지난 Job과 관련 파일을 삭제한다. 삭제된 수를 반환한다."""
        cutoff = time.time() - ttl
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM jobs WHERE created_at < ?", (cutoff,)
            ).fetchall()
            count = 0
            for row in rows:
                job_dir = jobs_dir / row["id"]
                if job_dir.is_dir():
                    shutil.rmtree(job_dir, ignore_errors=True)
                count += 1
            self._conn.execute("DELETE FROM jobs WHERE created_at < ?", (cutoff,))
            self._conn.commit()
        return count

    def ping(self) -> bool:
        """DB 연결 상태를 확인한다."""
        self._conn.execute("SELECT 1")
        return True

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_dict(row: dict[str, Any] | sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        if isinstance(d.get("result"), str):
            d["result"] = json.loads(d["result"])
        if isinstance(d.get("progress"), str):
            d["progress"] = json.loads(d["progress"])
        d.pop("created_at", None)
        return d
