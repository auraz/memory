import sqlite3
from dataclasses import dataclass
from typing import Protocol


DEFAULT_BLOCKS = {
    "human": (
        "Stable facts about the user: identity, role, preferences, constraints, and durable context.",
        3000,
    ),
    "persona": (
        "Stable behavior for Frakir: tone, boundaries, and how the assistant should work.",
        2000,
    ),
    "active_projects": (
        "Current projects and their compact status. Keep this focused and update stale items.",
        3000,
    ),
    "active_goal": (
        "The single active goal Frakir should keep in view across normal answers and tool routing.",
        1200,
    ),
    "preferences": (
        "User preferences for tools, communication, workflow, and decision-making.",
        2500,
    ),
    "current_focus": (
        "Short-lived working focus, current constraints, and what not to over-optimize.",
        1500,
    ),
}

BLOCK_RENDER_ORDER = {
    "human": 1,
    "persona": 2,
    "active_projects": 3,
    "active_goal": 4,
    "preferences": 5,
    "current_focus": 6,
}

BLOCK_RENDER_LIMITS = {
    "human": 700,
    "persona": 350,
    "active_projects": 900,
    "active_goal": 700,
    "preferences": 900,
    "current_focus": 800,
}


@dataclass(frozen=True)
class CoreMemoryBlock:
    label: str
    description: str
    value: str
    char_limit: int


class CoreMemory(Protocol):
    async def list_blocks(self) -> list[CoreMemoryBlock]:
        ...

    async def set_block(self, label: str, value: str, description: str | None = None, char_limit: int | None = None) -> None:
        ...

    async def render(self, max_chars: int) -> str:
        ...


class SQLiteCoreMemory:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.ensure_defaults()

    def ensure_defaults(self) -> None:
        for label, (description, char_limit) in DEFAULT_BLOCKS.items():
            self.conn.execute(
                """
                insert into core_memory_blocks (label, description, value, char_limit)
                values (?, ?, '', ?)
                on conflict(label) do nothing
                """,
                (label, description, char_limit),
            )
        self.conn.commit()

    async def list_blocks(self) -> list[CoreMemoryBlock]:
        rows = self.conn.execute(
            """
            select label, description, value, char_limit
            from core_memory_blocks
            order by
              case label
                when 'human' then 1
                when 'persona' then 2
                when 'active_projects' then 3
                when 'active_goal' then 4
                when 'preferences' then 5
                when 'current_focus' then 6
                else 20
              end,
              label
            """
        ).fetchall()
        return [
            CoreMemoryBlock(
                label=str(row["label"]),
                description=str(row["description"]),
                value=str(row["value"]),
                char_limit=int(row["char_limit"]),
            )
            for row in rows
        ]

    async def set_block(
        self,
        label: str,
        value: str,
        description: str | None = None,
        char_limit: int | None = None,
    ) -> None:
        normalized_label = normalize_block_label(label)
        existing = self.conn.execute(
            "select description, char_limit from core_memory_blocks where label = ?",
            (normalized_label,),
        ).fetchone()
        default_description = existing["description"] if existing else ""
        default_limit = int(existing["char_limit"]) if existing else 2000
        final_limit = char_limit or default_limit
        self.conn.execute(
            """
            insert into core_memory_blocks (label, description, value, char_limit, updated_at)
            values (?, ?, ?, ?, current_timestamp)
            on conflict(label) do update set
              description = excluded.description,
              value = excluded.value,
              char_limit = excluded.char_limit,
              updated_at = current_timestamp
            """,
            (
                normalized_label,
                description if description is not None else default_description,
                value[:final_limit],
                final_limit,
            ),
        )
        self.conn.commit()

    async def render(self, max_chars: int) -> str:
        return render_core_memory(await self.list_blocks(), max_chars=max_chars)


def render_core_memory(blocks: list[CoreMemoryBlock], max_chars: int) -> str:
    active_blocks = sorted(
        [block for block in blocks if block.value.strip()],
        key=lambda block: (BLOCK_RENDER_ORDER.get(block.label, 20), block.label),
    )
    if not active_blocks:
        return "Core memory blocks are empty."
    lines = [
        "Core memory blocks:",
        "These are stable, curated context. Treat them as higher priority than archive recall.",
    ]
    remaining = max_chars - sum(len(line) + 1 for line in lines)
    for block in active_blocks:
        if remaining <= 0:
            break
        value = " ".join(block.value.split())
        render_limit = BLOCK_RENDER_LIMITS.get(block.label, block.char_limit)
        value = value[: min(len(value), block.char_limit, render_limit, remaining)].rstrip()
        if not value:
            continue
        section = f"<{block.label}>\n{value}\n</{block.label}>"
        lines.append(section)
        remaining -= len(section) + 1
    return "\n".join(lines)


def normalize_block_label(label: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "_" for char in label.strip())
    normalized = "_".join(part for part in normalized.split("_") if part)
    if not normalized:
        raise ValueError("Core memory block label cannot be empty")
    return normalized
