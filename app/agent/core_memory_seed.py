import argparse
import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.agent.core_memory import CoreMemory, SQLiteCoreMemory
from app.agent.core_memory_updater import parse_core_memory_updates
from app.agent.letta_adapter import LettaCoreMemory
from app.memory.palace import DEFAULT_PALACE_DIR, extract_generated_content
from app.providers.base import LLMProvider
from app.providers.factory import create_provider
from app.settings import settings
from app.storage import connect, init_db


PALACE_FILES = {
    "about_me": "about_me.md",
    "cv": "cv.md",
    "active_projects": "active_projects.md",
    "preferences": "preferences.md",
    "open_loops": "open_loops.md",
}


@dataclass(frozen=True)
class CoreMemorySyncResult:
    updates: dict[str, str]
    palace_dir: Path
    dry_run: bool = False


def default_palace_dir() -> Path:
    obsidian_palace = settings.obsidian_vault_path / "Frakir Palace"
    if obsidian_palace.expanduser().exists():
        return obsidian_palace
    return DEFAULT_PALACE_DIR


def load_palace_rooms(palace_dir: Path) -> dict[str, str]:
    rooms: dict[str, str] = {}
    for name, filename in PALACE_FILES.items():
        path = palace_dir.expanduser() / filename
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        generated = extract_generated_content(raw)
        rooms[name] = generated or raw.strip()
    return rooms


def build_sync_prompt(rooms: dict[str, str], current_core_memory: str) -> str:
    room_text = "\n\n".join(f"<{name}>\n{text}\n</{name}>" for name, text in rooms.items() if text.strip())
    return (
        "Sync Frakir Letta/core memory blocks from curated memory palace rooms.\n"
        "The palace is the durable human-readable memory layer. Core memory is the compact always-visible layer.\n"
        "Update only blocks that should change. Keep every block compact. Preserve stable current facts from existing core memory unless the palace clearly supersedes them.\n"
        "Do not include citations, source markers, draft metadata, uncertain claims, timestamps, or long lists.\n"
        "Do not overwrite persona unless the palace clearly says how Frakir should behave.\n\n"
        "Return strict JSON only:\n"
        "{\"updates\":{\"human\":\"...\",\"active_projects\":\"...\",\"preferences\":\"...\",\"current_focus\":\"...\"}}\n\n"
        "Target blocks:\n"
        "- human: 2-3 sentences, stable identity/user facts only, max 500 chars.\n"
        "- active_projects: max 5 bullets, only genuinely active themes, max 700 chars.\n"
        "- preferences: max 6 compact bullets, stable preferences only, max 700 chars.\n"
        "- current_focus: max 5 bullets, immediate priorities/open loops only, max 600 chars.\n"
        "- persona: only if explicit Frakir behavior guidance, max 300 chars.\n\n"
        "Current core memory:\n"
        f"{current_core_memory}\n\n"
        "Memory palace rooms:\n"
        f"{room_text or '(no palace rooms found)'}\n\n"
        "JSON:"
    )


async def sync_core_memory_from_palace(
    core_memory: CoreMemory,
    provider: LLMProvider,
    palace_dir: Path,
    dry_run: bool = False,
) -> CoreMemorySyncResult:
    rooms = load_palace_rooms(palace_dir)
    if not rooms:
        return CoreMemorySyncResult(updates={}, palace_dir=palace_dir, dry_run=dry_run)

    current = await core_memory.render(settings.core_memory_chars)
    raw = await provider.complete(
        "You are a precise memory curator. Return strict JSON only.",
        build_sync_prompt(rooms, current),
    )
    updates = parse_core_memory_updates(raw)
    if not dry_run:
        for label, value in updates.items():
            await core_memory.set_block(label, value)
    return CoreMemorySyncResult(updates=updates, palace_dir=palace_dir, dry_run=dry_run)


async def seed_core_memory_from_palace(
    core_memory: CoreMemory,
    provider: LLMProvider,
    palace_dir: Path,
    dry_run: bool = False,
) -> CoreMemorySyncResult:
    return await sync_core_memory_from_palace(core_memory, provider, palace_dir, dry_run=dry_run)


def build_configured_core_memory(conn: sqlite3.Connection) -> CoreMemory:
    local = SQLiteCoreMemory(conn)
    if settings.letta_enabled and settings.letta_agent_id:
        return LettaCoreMemory(
            agent_id=settings.letta_agent_id,
            api_key=settings.letta_api_key,
            base_url=settings.letta_base_url,
            fallback=local,
        )
    return local


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Sync Letta/core memory from Frakir Palace room files.")
    parser.add_argument("--palace-dir", type=Path, default=default_palace_dir())
    parser.add_argument("--dry-run", action="store_true", help="Print proposed updates without writing them.")
    args = parser.parse_args()

    init_db(settings.sqlite_path)
    with connect(settings.sqlite_path) as conn:
        core_memory = build_configured_core_memory(conn)
        result = await sync_core_memory_from_palace(
            core_memory=core_memory,
            provider=create_provider(settings),
            palace_dir=args.palace_dir,
            dry_run=args.dry_run,
        )

    if not result.updates:
        print(f"No core memory updates produced from {result.palace_dir}.")
        return
    action = "Would update" if result.dry_run else "Updated"
    print(f"{action} {len(result.updates)} core memory block(s) from {result.palace_dir}:")
    for label, value in result.updates.items():
        print(f"- {label}: {value[:240]}")


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
