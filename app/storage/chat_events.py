import sqlite3
from dataclasses import dataclass
from datetime import datetime


MAX_EVENT_CHARS = 700


@dataclass(frozen=True)
class ChatEvent:
    role: str
    content: str
    created_at: str


class ChatEventStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def append(self, telegram_chat_id: str, role: str, content: str, local_date: str | None = None) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        self.conn.execute(
            """
            insert into chat_events (telegram_chat_id, local_date, role, content, created_at)
            values (?, ?, ?, ?, current_timestamp)
            """,
            (telegram_chat_id, local_date or self.today(), role, content),
        )
        self.conn.commit()

    def today_events(
        self,
        telegram_chat_id: str,
        local_date: str | None = None,
        limit: int = 12,
    ) -> list[ChatEvent]:
        rows = self.conn.execute(
            """
            select role, content, created_at
            from chat_events
            where telegram_chat_id = ? and local_date = ?
            order by id desc
            limit ?
            """,
            (telegram_chat_id, local_date or self.today(), limit),
        ).fetchall()
        return [
            ChatEvent(role=str(row["role"]), content=str(row["content"]), created_at=str(row["created_at"]))
            for row in reversed(rows)
        ]

    def today_context(
        self,
        telegram_chat_id: str,
        local_date: str | None = None,
        limit: int = 12,
        max_chars: int = 1800,
        max_event_chars: int = MAX_EVENT_CHARS,
    ) -> str:
        events = self.today_events(telegram_chat_id, local_date=local_date, limit=limit)
        if not events:
            return "No prior Telegram messages with the bot today."

        lines = ["Today with this Telegram chat:"]
        for event in events:
            role = "User" if event.role == "user" else "Bot"
            lines.append(f"- {role}: {_compact(event.content, max_event_chars)}")
        return _compact("\n".join(lines), max_chars)

    def clear_chat(self, telegram_chat_id: str) -> None:
        self.conn.execute("delete from chat_events where telegram_chat_id = ?", (telegram_chat_id,))
        self.conn.commit()

    @staticmethod
    def today() -> str:
        return datetime.now().astimezone().date().isoformat()


def _compact(text: str, max_chars: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."
