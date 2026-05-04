import json
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PendingAction:
    id: int
    tool_name: str
    payload: dict[str, Any]
    status: str


class ApprovalQueue:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create(self, tool_name: str, payload: dict[str, Any]) -> int:
        cursor = self.conn.execute(
            "insert into pending_actions (tool_name, payload_json) values (?, ?)",
            (tool_name, json.dumps(payload, ensure_ascii=True)),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def list_pending(self) -> list[PendingAction]:
        rows = self.conn.execute(
            """
            select id, tool_name, payload_json, status
            from pending_actions
            where status = 'pending'
            order by id asc
            """
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_pending(self, action_id: int) -> PendingAction | None:
        row = self.conn.execute(
            """
            select id, tool_name, payload_json, status
            from pending_actions
            where id = ? and status = 'pending'
            """,
            (action_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    def mark(self, action_id: int, status: str) -> None:
        if status not in {"approved", "denied"}:
            raise ValueError("status must be approved or denied")
        self.conn.execute(
            """
            update pending_actions
            set status = ?, decided_at = current_timestamp
            where id = ? and status = 'pending'
            """,
            (status, action_id),
        )
        self.conn.commit()

    def _from_row(self, row: sqlite3.Row) -> PendingAction:
        return PendingAction(
            id=int(row["id"]),
            tool_name=str(row["tool_name"]),
            payload=json.loads(row["payload_json"]),
            status=str(row["status"]),
        )
