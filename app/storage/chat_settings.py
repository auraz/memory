import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatSettings:
    telegram_chat_id: str
    skill_name: str | None


class ChatSettingsStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, telegram_chat_id: str) -> ChatSettings:
        row = self.conn.execute(
            "select telegram_chat_id, skill_name from chat_settings where telegram_chat_id = ?",
            (telegram_chat_id,),
        ).fetchone()
        if row is None:
            return ChatSettings(telegram_chat_id=telegram_chat_id, skill_name=None)
        return ChatSettings(
            telegram_chat_id=str(row["telegram_chat_id"]),
            skill_name=str(row["skill_name"]) if row["skill_name"] else None,
        )

    def set_skill(self, telegram_chat_id: str, skill_name: str | None) -> None:
        self.conn.execute(
            """
            insert into chat_settings (telegram_chat_id, skill_name, updated_at)
            values (?, ?, current_timestamp)
            on conflict(telegram_chat_id) do update set
              skill_name = excluded.skill_name,
              updated_at = current_timestamp
            """,
            (telegram_chat_id, skill_name),
        )
        self.conn.commit()
