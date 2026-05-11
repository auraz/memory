import argparse
import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.memory.cognee_store import CogneeMemory, MemoryItem
from app.providers.base import LLMProvider
from app.providers.factory import create_provider
from app.runtime_limits import raise_file_descriptor_limit
from app.settings import settings


DEFAULT_PALACE_DIR = Path("data/palace")
PALACE_INBOX_FILENAME = "inbox.md"
GENERATED_BEGIN = "<!-- FRAKIR:BEGIN generated -->"
GENERATED_END = "<!-- FRAKIR:END generated -->"
MEMORY_MARKER_RE = re.compile(r"\s*\[M\d+(?:\s+[^\]]+)?\]")


@dataclass(frozen=True)
class PalaceRoomSpec:
    name: str
    filename: str
    title: str
    recall_queries: tuple[str, ...]
    sections: tuple[str, ...]


ROOMS: tuple[PalaceRoomSpec, ...] = (
    PalaceRoomSpec(
        name="about_me",
        filename="about_me.md",
        title="About Me",
        recall_queries=(
            "about me identity biography work style personal preferences",
            "user profile role location communication style",
            "important facts about the user",
        ),
        sections=("Identity", "Working Style", "Current Focus", "Stable Personal Facts"),
    ),
    PalaceRoomSpec(
        name="cv",
        filename="cv.md",
        title="CV",
        recall_queries=(
            "CV resume professional experience skills achievements",
            "career roles companies engineering leadership projects",
            "portfolio accomplishments technical stack",
        ),
        sections=("Professional Summary", "Core Skills", "Experience Themes", "Projects"),
    ),
    PalaceRoomSpec(
        name="active_projects",
        filename="active_projects.md",
        title="Active Projects",
        recall_queries=(
            "active projects current development project goals",
            "Frakir memory agent current work open tasks",
            "LLM learning workflow improvements current projects",
        ),
        sections=("Projects", "Status", "Goals", "Open Loops"),
    ),
    PalaceRoomSpec(
        name="preferences",
        filename="preferences.md",
        title="Preferences",
        recall_queries=(
            "user preferences communication style tools workflow",
            "preferences local first Telegram Mac approvals memory",
            "how user likes assistants to respond and work",
        ),
        sections=("Communication", "Tools", "Workflow", "Memory Preferences"),
    ),
    PalaceRoomSpec(
        name="open_loops",
        filename="open_loops.md",
        title="Open Loops",
        recall_queries=(
            "open loops TODO next actions pending decisions",
            "unfinished projects blockers follow up",
            "current tasks unresolved questions",
        ),
        sections=("Immediate Next Actions", "Pending Decisions", "Risks", "Follow-ups"),
    ),
)

ROOMS_BY_NAME = {room.name: room for room in ROOMS}
ROOMS_BY_FILENAME = {room.filename: room for room in ROOMS}


async def build_palace(
    memory: CogneeMemory | None = None,
    provider: LLMProvider | None = None,
    output_dir: Path = DEFAULT_PALACE_DIR,
    ingest: bool = False,
) -> list[Path]:
    memory = memory or CogneeMemory(max_items=settings.max_context_items)
    provider = provider or create_provider(settings)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for room in ROOMS:
        print(f"Building palace room: {room.name}", flush=True)
        context = await collect_room_context(memory, room)
        path = output_dir / room.filename
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        manual_content = extract_manual_content(existing)
        previous_generated = extract_generated_content(existing)
        draft = await synthesize_room(provider, room, context, previous_generated, manual_content)
        rendered = render_room(room, draft, existing)
        if not path.exists() or path.read_text(encoding="utf-8") != rendered:
            path.write_text(rendered, encoding="utf-8")
            print(f"Wrote {path}", flush=True)
        else:
            print(f"Unchanged {path}", flush=True)
        written.append(path)
        if ingest:
            await memory.remember(path.read_text(encoding="utf-8"), source=f"palace:{room.name}")
            print(f"Ingested {room.name} into memory", flush=True)
    return written


async def collect_room_context(memory: CogneeMemory, room: PalaceRoomSpec) -> str:
    blocks: list[str] = []
    for query in room.recall_queries:
        items, error = await memory.safe_recall(query)
        if error:
            blocks.append(f"Query: {query}\nRecall error: {error}")
            continue
        blocks.append(f"Query: {query}\n{format_memory_items(items)}")
    return "\n\n---\n\n".join(blocks)


def format_memory_items(items: list[MemoryItem]) -> str:
    if not items:
        return "No recalled items."
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        source = f" source={item.source}" if item.source else ""
        lines.append(f"[M{index}{source}]\n{item.text}")
    return "\n\n".join(lines)


async def synthesize_room(
    provider: LLMProvider,
    room: PalaceRoomSpec,
    context: str,
    previous_generated: str = "",
    manual_content: str = "",
) -> str:
    system = (
        "You write curated memory palace room files for a local personal AI agent. "
        "Use only the recalled context. Do not invent facts. If evidence is weak, mark it as uncertain. "
        "Return concise Markdown with the requested sections. Do not include source labels, citation markers, "
        "or footnote-style references such as [M1]. This is a draft for user review, not final truth. "
        "Evolve the previous generated room instead of rewriting from scratch. Preserve stable facts, update stale "
        "facts, add new evidence-backed facts, and keep unresolved uncertainty explicit. Respect manual notes as "
        "higher-priority user-curated context, but return only the generated room block."
    )
    user = (
        f"Update the `{room.name}` room.\n"
        f"Title: {room.title}\n"
        f"Required sections: {', '.join(room.sections)}\n\n"
        "Previous generated room:\n"
        f"{previous_generated or '(none)'}\n\n"
        "Manual/user-edited content outside generated block:\n"
        f"{manual_content or '(none)'}\n\n"
        "Recalled context:\n"
        f"{context}"
    )
    result = await provider.complete(system, user)
    return result.strip() or "_No useful memory recalled yet._"


def render_room(room: PalaceRoomSpec, draft: str, existing: str = "") -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    clean_draft = strip_memory_markers(draft).strip()
    generated_block = (
        f"{GENERATED_BEGIN}\n"
        f"Generated: {generated}\n"
        "Status: draft\n"
        "Source: Frakir palace-build\n\n"
        f"{clean_draft}\n"
        f"\n{GENERATED_END}"
    )
    if existing:
        before, _old_generated, after = split_generated_block(existing)
        header = before.strip() or f"# {room.title}"
        tail = after.strip()
        return f"{header}\n\n{generated_block}\n" + (f"\n{tail}\n" if tail else "\n")
    return f"# {room.title}\n\n{generated_block}\n"


def split_generated_block(text: str) -> tuple[str, str, str]:
    start = text.find(GENERATED_BEGIN)
    if start == -1:
        return text, "", ""
    end = text.find(GENERATED_END, start)
    if end == -1:
        return text, "", ""
    end += len(GENERATED_END)
    return text[:start], text[start:end], text[end:]


def strip_memory_markers(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        cleaned = MEMORY_MARKER_RE.sub("", line)
        cleaned = re.sub(r" {2,}", " ", cleaned).rstrip()
        if cleaned.strip().lower() in {"sources:", "source:"}:
            continue
        lines.append(cleaned)
    return "\n".join(lines)


def extract_generated_content(text: str) -> str:
    _before, generated, _after = split_generated_block(text)
    if not generated:
        return ""
    body = generated.replace(GENERATED_BEGIN, "", 1).replace(GENERATED_END, "", 1).strip()
    lines = [
        line
        for line in body.splitlines()
        if not line.startswith("Generated: ")
        and not line.startswith("Status: ")
        and not line.startswith("Source: ")
    ]
    return "\n".join(lines).strip()


def extract_manual_content(text: str) -> str:
    before, _generated, after = split_generated_block(text)
    manual = "\n\n".join(part.strip() for part in (before, after) if part.strip())
    lines = [line for line in manual.splitlines() if not line.startswith("# ")]
    return "\n".join(lines).strip()


def append_palace_memory(text: str, output_dir: Path, room_name: str | None = None) -> Path:
    memory = " ".join(text.split())
    if not memory:
        raise ValueError("Memory text cannot be empty")
    output_dir.expanduser().mkdir(parents=True, exist_ok=True)
    room = ROOMS_BY_NAME.get(room_name or infer_palace_room(memory))
    if room is None:
        path = output_dir.expanduser() / PALACE_INBOX_FILENAME
        title = "Memory Inbox"
    else:
        path = output_dir.expanduser() / room.filename
        title = room.title

    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {title}\n"
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    section = "\n\n## Remembered\n" if "## Remembered" not in existing else ""
    entry = f"{section}- {timestamp}: {memory}\n"
    path.write_text(existing.rstrip() + "\n" + entry, encoding="utf-8")
    return path


def infer_palace_room(text: str) -> str | None:
    lower = text.lower()
    if any(token in lower for token in ("prefer", "preference", "preferences", "like answers", "communication style")):
        return "preferences"
    if any(token in lower for token in ("goal", "project", "building", "implement", "ship", "frakir", "openclaw")):
        return "active_projects"
    if any(token in lower for token in ("todo", "to do", "next", "follow up", "open loop", "blocker")):
        return "open_loops"
    if any(token in lower for token in ("cv", "resume", "career", "lyft", "role", "experience")):
        return "cv"
    if any(token in lower for token in ("about me", "identity", "i am", "my background")):
        return "about_me"
    return None


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Build curated memory palace room files from current memory recall.")
    parser.add_argument("--output", type=Path, default=DEFAULT_PALACE_DIR)
    parser.add_argument("--ingest", action="store_true", help="Also ingest generated palace files into Cognee.")
    args = parser.parse_args()
    soft_limit, hard_limit = raise_file_descriptor_limit()
    print(f"Open file limit: soft={soft_limit} hard={hard_limit}", flush=True)
    paths = await build_palace(output_dir=args.output, ingest=args.ingest)
    print(f"Built {len(paths)} palace room files in {args.output}.")


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
