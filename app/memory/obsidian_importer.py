import argparse
import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from app.memory.cognee_store import CogneeMemory
from app.settings import settings


IGNORED_DIRS = {".git", ".obsidian", ".trash", "node_modules"}
MAX_UNBROKEN_LINE_CHARS = 2000
MAX_NOTE_CHARS_PER_MEMORY = 6000
BASE64ISH_RE = re.compile(r"^[A-Za-z0-9+/=\s]{200,}$")
FORBIDDEN_PAYLOAD_MARKERS = ["```compressed-json", "compressed-json", "## Drawing"]
COGNEE_MAX_WORD_CHARS = 8191


@dataclass(frozen=True)
class SanitizedNote:
    content: str
    removed_lines: int = 0
    removed_blocks: int = 0


def iter_markdown_files(vault_path: Path) -> list[Path]:
    vault_path = vault_path.expanduser().resolve()
    if not vault_path.exists():
        raise FileNotFoundError(f"Obsidian vault path does not exist: {vault_path}")
    if not vault_path.is_dir():
        raise NotADirectoryError(f"Obsidian vault path is not a directory: {vault_path}")

    files: list[Path] = []
    for path in vault_path.rglob("*.md"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        files.append(path)
    return sorted(files)


def read_note_readonly(path: Path) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def sanitize_note(content: str) -> SanitizedNote:
    kept: list[str] = []
    removed = 0
    removed_blocks = 0
    in_dropped_fence = False
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped == "%%" and _starts_excalidraw_drawing_block(lines, index):
            removed_blocks += 1
            removed += 1
            index += 1
            while index < len(lines):
                removed += 1
                if lines[index].strip() == "%%":
                    index += 1
                    break
                index += 1
            continue

        if stripped == "## Drawing":
            removed_blocks += 1
            removed += 1
            index += 1
            while index < len(lines):
                removed += 1
                if lines[index].strip() == "%%":
                    index += 1
                    break
                index += 1
            continue

        if in_dropped_fence:
            if stripped.startswith("```"):
                in_dropped_fence = False
            removed += 1
            index += 1
            continue

        if stripped.startswith("```compressed-json"):
            in_dropped_fence = True
            removed_blocks += 1
            removed += 1
            index += 1
            continue

        is_too_long = len(stripped) > MAX_UNBROKEN_LINE_CHARS
        looks_encoded = bool(BASE64ISH_RE.match(stripped)) and " " not in stripped[:300]
        if is_too_long or looks_encoded:
            removed += 1
            index += 1
            continue
        kept.append(line)
        index += 1
    return SanitizedNote(
        content="\n".join(kept).strip(),
        removed_lines=removed,
        removed_blocks=removed_blocks,
    )


def _starts_excalidraw_drawing_block(lines: list[str], index: int) -> bool:
    preview = "\n".join(line.strip() for line in lines[index + 1 : index + 8])
    return "## Drawing" in preview or "```compressed-json" in preview


def chunk_text(text: str, max_chars: int = MAX_NOTE_CHARS_PER_MEMORY) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in text.split("\n\n"):
        paragraph_len = len(paragraph) + 2
        if current and current_len + paragraph_len > max_chars:
            chunks.append("\n\n".join(current).strip())
            current = []
            current_len = 0
        if paragraph_len > max_chars:
            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start : start + max_chars].strip())
            continue
        current.append(paragraph)
        current_len += paragraph_len
    if current:
        chunks.append("\n\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def validate_cognee_payload(payload: str) -> None:
    for marker in FORBIDDEN_PAYLOAD_MARKERS:
        if marker in payload:
            raise ValueError(f"Sanitizer leak before Cognee ingest: {marker}")
    longest = max((len(token) for token in payload.split()), default=0)
    if longest > COGNEE_MAX_WORD_CHARS:
        raise ValueError(f"Sanitizer leak before Cognee ingest: token length {longest}")


ProgressCallback = Callable[[int, int, Path], Awaitable[None]]
FailureCallback = Callable[[int, int, Path, Exception], Awaitable[None]]


async def ingest_obsidian(
    vault_path: Path,
    memory: CogneeMemory,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
    failure: FailureCallback | None = None,
    note_paths: list[Path] | None = None,
    skip_errors: bool = False,
) -> int:
    count = 0
    processed = 0
    note_paths = note_paths or iter_markdown_files(vault_path)
    if limit is not None:
        note_paths = note_paths[:limit]
    total = len(note_paths)
    for note_path in note_paths:
        if limit is not None and processed >= limit:
            break
        processed += 1
        try:
            content = read_note_readonly(note_path)
            sanitized = sanitize_note(content)
            if sanitized.content:
                chunks = chunk_text(sanitized.content)
                for index, chunk in enumerate(chunks, start=1):
                    chunk_label = f" chunk {index}/{len(chunks)}" if len(chunks) > 1 else ""
                    removed_label = (
                        "\n"
                        + ", ".join(
                            item
                            for item in [
                                (
                                    f"Removed encoded/oversized lines: {sanitized.removed_lines}"
                                    if sanitized.removed_lines
                                    else ""
                                ),
                                (
                                    f"Removed compressed blocks: {sanitized.removed_blocks}"
                                    if sanitized.removed_blocks
                                    else ""
                                ),
                            ]
                            if item
                        )
                        if sanitized.removed_lines or sanitized.removed_blocks
                        else ""
                    )
                    payload = f"Source: {note_path}{chunk_label}{removed_label}\n\n{chunk}"
                    validate_cognee_payload(payload)
                    await memory.remember(payload, source=str(note_path))
            count += 1
            if progress is not None:
                await progress(processed, total, note_path)
        except Exception as exc:
            if failure is not None:
                await failure(processed, total, note_path, exc)
            if not skip_errors:
                raise
    return count


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Obsidian vault ingestion into Cognee.")
    parser.add_argument("--vault", type=Path, default=settings.obsidian_vault_path)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    memory = CogneeMemory(max_items=settings.max_context_items)
    count = await ingest_obsidian(args.vault, memory, limit=args.limit)
    print(f"Ingested {count} markdown notes from {args.vault}")


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
