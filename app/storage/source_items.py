import sqlite3


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

    def mark(self, source: str, item_id: str, fingerprint: str, status: str, message: str = "") -> None:
        if status not in {"completed", "failed"}:
            raise ValueError("status must be completed or failed")
        self.conn.execute(
            """
            insert into imported_source_items (source, item_id, fingerprint, status, message, updated_at)
            values (?, ?, ?, ?, ?, current_timestamp)
            on conflict(source, item_id) do update set
              fingerprint = excluded.fingerprint,
              status = excluded.status,
              message = excluded.message,
              updated_at = current_timestamp
            """,
            (source, item_id, fingerprint, status, message[:1000]),
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
