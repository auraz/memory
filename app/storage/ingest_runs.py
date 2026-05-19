import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IngestRun:
    id: int
    source: str
    status: str
    total_files: int
    processed_files: int
    message: str
    updated_at: str


class IngestRunStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def start(self, source: str, total_files: int) -> int:
        cursor = self.conn.execute(
            """
            insert into ingest_runs (source, status, total_files, processed_files, message)
            values (?, 'running', ?, 0, '')
            """,
            (source, total_files),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def update(self, run_id: int, processed_files: int, message: str = "") -> None:
        self.conn.execute(
            """
            update ingest_runs
            set processed_files = ?, message = ?, updated_at = current_timestamp
            where id = ?
            """,
            (processed_files, message, run_id),
        )
        self.conn.commit()

    def finish(self, run_id: int, status: str, message: str = "") -> None:
        if status not in {"completed", "completed_with_failures", "failed"}:
            raise ValueError("status must be completed, completed_with_failures, or failed")
        self.conn.execute(
            """
            update ingest_runs
            set status = ?, message = ?, updated_at = current_timestamp, finished_at = current_timestamp
            where id = ?
            """,
            (status, message, run_id),
        )
        self.conn.commit()

    def latest(self) -> IngestRun | None:
        row = self.conn.execute(
            """
            select id, source, status, total_files, processed_files, message, updated_at
            from ingest_runs
            order by id desc
            limit 1
            """
        ).fetchone()
        if row is None:
            return None
        return IngestRun(
            id=int(row["id"]),
            source=str(row["source"]),
            status=str(row["status"]),
            total_files=int(row["total_files"]),
            processed_files=int(row["processed_files"]),
            message=str(row["message"]),
            updated_at=str(row["updated_at"]),
        )

    def abandon_running(self, message: str = "Abandoned after process restart.") -> int:
        cursor = self.conn.execute(
            """
            update ingest_runs
            set status = 'failed',
                message = ?,
                updated_at = current_timestamp,
                finished_at = current_timestamp
            where status = 'running'
            """,
            (message,),
        )
        self.conn.commit()
        return int(cursor.rowcount)

    def is_file_terminal(self, path: Path) -> bool:
        resolved = str(path.resolve())
        stat = path.stat()
        row = self.conn.execute(
            """
            select status
            from ingested_files
            where path = ? and size_bytes = ? and mtime_ns = ? and status in ('completed', 'failed')
            """,
            (resolved, stat.st_size, stat.st_mtime_ns),
        ).fetchone()
        return row is not None

    def is_file_completed(self, path: Path) -> bool:
        resolved = str(path.resolve())
        stat = path.stat()
        row = self.conn.execute(
            """
            select status
            from ingested_files
            where path = ? and size_bytes = ? and mtime_ns = ? and status = 'completed'
            """,
            (resolved, stat.st_size, stat.st_mtime_ns),
        ).fetchone()
        return row is not None

    def mark_file_completed(self, path: Path, run_id: int) -> None:
        self._mark_file(path, run_id, "completed")

    def mark_file_failed(self, path: Path, run_id: int, error: str) -> None:
        self._mark_file(path, run_id, "failed")

    def _mark_file(self, path: Path, run_id: int, status: str, error: str = "") -> None:
        resolved = str(path.resolve())
        stat = path.stat()
        self.conn.execute(
            """
            insert into ingested_files (path, size_bytes, mtime_ns, status, run_id, updated_at)
            values (?, ?, ?, ?, ?, current_timestamp)
            on conflict(path) do update set
              size_bytes = excluded.size_bytes,
              mtime_ns = excluded.mtime_ns,
              status = excluded.status,
              run_id = excluded.run_id,
              updated_at = current_timestamp
            """,
            (resolved, stat.st_size, stat.st_mtime_ns, status, run_id),
        )
        self.conn.commit()

    def completed_count(self) -> int:
        row = self.conn.execute(
            "select count(*) as count from ingested_files where status = 'completed'"
        ).fetchone()
        return int(row["count"])

    def failed_count(self) -> int:
        row = self.conn.execute(
            "select count(*) as count from ingested_files where status = 'failed'"
        ).fetchone()
        return int(row["count"])

    def terminal_count(self) -> int:
        row = self.conn.execute(
            "select count(*) as count from ingested_files where status in ('completed', 'failed')"
        ).fetchone()
        return int(row["count"])

    def clear_manifest(self) -> None:
        self.conn.execute("delete from ingested_files")
        self.conn.execute(
            """
            insert into ingest_runs (source, status, total_files, processed_files, message, finished_at)
            values ('local', 'completed', 0, 0, 'Cleared ingest manifest.', current_timestamp)
            """
        )
        self.conn.commit()
