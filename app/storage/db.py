import sqlite3
from pathlib import Path


SCHEMA = """
create table if not exists pending_actions (
  id integer primary key autoincrement,
  tool_name text not null,
  payload_json text not null,
  status text not null default 'pending',
  created_at text not null default current_timestamp,
  decided_at text
);

create table if not exists chat_events (
  id integer primary key autoincrement,
  telegram_chat_id text not null,
  local_date text not null default '',
  role text not null,
  content text not null,
  created_at text not null default current_timestamp
);

create table if not exists ingest_runs (
  id integer primary key autoincrement,
  source text not null,
  status text not null,
  total_files integer not null default 0,
  processed_files integer not null default 0,
  message text not null default '',
  started_at text not null default current_timestamp,
  updated_at text not null default current_timestamp,
  finished_at text
);

create table if not exists ingested_files (
  path text primary key,
  size_bytes integer not null,
  mtime_ns integer not null,
  status text not null,
  run_id integer,
  updated_at text not null default current_timestamp
);

create table if not exists chat_settings (
  telegram_chat_id text primary key,
  skill_name text,
  updated_at text not null default current_timestamp
);

create table if not exists imported_source_items (
  source text not null,
  item_id text not null,
  fingerprint text not null,
  size_bytes integer not null default 0,
  mtime_ns integer not null default 0,
  status text not null,
  message text not null default '',
  content_text text not null default '',
  updated_at text not null default current_timestamp,
  primary key (source, item_id)
);

"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Path) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        _ensure_column(conn, "chat_events", "local_date", "text not null default ''")
        _ensure_column(conn, "imported_source_items", "content_text", "text not null default ''")
        _ensure_column(conn, "imported_source_items", "size_bytes", "integer not null default 0")
        _ensure_column(conn, "imported_source_items", "mtime_ns", "integer not null default 0")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {definition}")
