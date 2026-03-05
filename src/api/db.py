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


class UserStore:
    """SQLite 기반 사용자 저장소."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                hashed_password TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)"
        )
        self._conn.commit()

    def create(
        self,
        user_id: str,
        username: str,
        hashed_password: str,
    ) -> dict[str, Any]:
        user = {
            "id": user_id,
            "username": username,
            "hashed_password": hashed_password,
            "created_at": time.time(),
        }
        with self._lock:
            self._conn.execute(
                "INSERT INTO users (id, username, hashed_password, created_at)"
                " VALUES (:id, :username, :hashed_password, :created_at)",
                user,
            )
            self._conn.commit()
        return {"id": user_id, "username": username}

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if row is None:
            return None
        return dict(row)


class RefreshTokenStore:
    """SQLite 기반 refresh token 저장소."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = conn
        self._lock = lock
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_rt_user ON refresh_tokens(user_id)"
        )
        self._conn.commit()

    def create(self, token_id: str, user_id: str, expires_at: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO refresh_tokens (token_id, user_id, expires_at)"
                " VALUES (?, ?, ?)",
                (token_id, user_id, expires_at),
            )
            self._conn.commit()

    def get(self, token_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM refresh_tokens WHERE token_id = ? AND revoked = 0",
                (token_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def revoke(self, token_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE refresh_tokens SET revoked = 1 WHERE token_id = ?",
                (token_id,),
            )
            self._conn.commit()

    def revoke_all_for_user(self, user_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ?",
                (user_id,),
            )
            self._conn.commit()


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
        self.users = UserStore(self._conn, self._lock)
        self.refresh_tokens = RefreshTokenStore(self._conn, self._lock)

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
        for col in (
            "progress",
            "dense_ply_path",
            "gs_splat_path",
            "potree_dir",
            "user_id",
        ):
            if col not in columns:
                self._conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
        if "user_id" not in columns:
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id)"
            )
        self._conn.commit()

    def create(
        self,
        job_id: str,
        status: str,
        url: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
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
            "user_id": user_id,
            "created_at": time.time(),
        }
        sql = (
            "INSERT INTO jobs"
            " (id, status, url, error, result, ply_path,"
            " dense_ply_path, gs_splat_path, potree_dir,"
            " progress, user_id, created_at)"
            " VALUES (:id, :status, :url, :error, :result,"
            " :ply_path, :dense_ply_path, :gs_splat_path,"
            " :potree_dir, :progress, :user_id, :created_at)"
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
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Job 목록을 조회한다. 최신순 정렬, 페이지네이션 지원."""
        params: list[Any] = []
        conditions: list[str] = []
        if status is not None:
            conditions.append("status = ?")
            params.append(status)
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        with self._lock:
            count_row = self._conn.execute(
                f"SELECT COUNT(*) FROM jobs{where}",
                params,  # noqa: S608
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

    def delete(self, job_id: str) -> bool:
        """Job 레코드를 삭제한다. 삭제 성공 시 True를 반환한다."""
        with self._lock:
            cursor = self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self._conn.commit()
            return cursor.rowcount > 0

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

    def fail_stale_jobs(self, statuses: list[str], error: str) -> int:
        """지정된 상태의 Job을 모두 failed로 전환한다. 전환된 수를 반환한다."""
        placeholders = ", ".join("?" for _ in statuses)
        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE jobs SET status = 'failed', error = ?"  # noqa: S608
                f" WHERE status IN ({placeholders})",
                [error, *statuses],
            )
            self._conn.commit()
            return cursor.rowcount

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
