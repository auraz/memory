import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceItemRecord:
    source: str
    item_id: str
    fingerprint: str
    size_bytes: int
    mtime_ns: int
    status: str
    message: str
    content_text: str


class SourceItemStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def is_terminal(self, source: str, item_id: str, fingerprint: str) -> bool:
        row = self.conn.execute(
            """
            select status
            from imported_source_items
            where source = ? and item_id = ? and fingerprint = ? and status in ('completed', 'failed')
            """,
            (source, item_id, fingerprint),
        ).fetchone()
        return row is not None

    def get(self, source: str, item_id: str) -> SourceItemRecord | None:
        row = self.conn.execute(
            """
            select source, item_id, fingerprint, size_bytes, mtime_ns, status, message, content_text
            from imported_source_items
            where source = ? and item_id = ?
            """,
            (source, item_id),
        ).fetchone()
        if row is None:
            return None
        return SourceItemRecord(
            source=str(row["source"]),
            item_id=str(row["item_id"]),
            fingerprint=str(row["fingerprint"]),
            size_bytes=int(row["size_bytes"] or 0),
            mtime_ns=int(row["mtime_ns"] or 0),
            status=str(row["status"]),
            message=str(row["message"]),
            content_text=str(row["content_text"] or ""),
        )

    def mark(
        self,
        source: str,
        item_id: str,
        fingerprint: str,
        status: str,
        message: str = "",
        content_text: str = "",
        size_bytes: int = 0,
        mtime_ns: int = 0,
    ) -> None:
        if status not in {"completed", "failed"}:
            raise ValueError("status must be completed or failed")
        self.conn.execute(
            """
            insert into imported_source_items (
              source, item_id, fingerprint, size_bytes, mtime_ns, status, message, content_text, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
            on conflict(source, item_id) do update set
              fingerprint = excluded.fingerprint,
              size_bytes = excluded.size_bytes,
              mtime_ns = excluded.mtime_ns,
              status = excluded.status,
              message = excluded.message,
              content_text = excluded.content_text,
              updated_at = current_timestamp
            """,
            (source, item_id, fingerprint, size_bytes, mtime_ns, status, message[:1000], content_text),
        )
        self.conn.commit()

    def count(self, source: str, status: str | None = None) -> int:
        if status is None:
            row = self.conn.execute(
                "select count(*) as count from imported_source_items where source = ?",
                (source,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "select count(*) as count from imported_source_items where source = ? and status = ?",
                (source, status),
            ).fetchone()
        return int(row["count"])

    def clear(self) -> None:
        self.conn.execute("delete from imported_source_items")
        self.conn.commit()
