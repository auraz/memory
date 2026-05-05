import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.memory.cognee_store import CogneeMemory
from app.memory.obsidian_importer import chunk_text, sanitize_note, validate_cognee_payload
from app.settings import settings


LOCAL_MEMORY_SOURCE = "local_memory"
TEXT_SUFFIXES = {".md", ".qmd", ".txt", ".json", ".jsonl"}
OPENCLAW_ROOT_FILES = [
    "IDENTITY.md",
    "SOUL.md",
    "USER.md",
    "TOOLS.md",
    "MEMORY.md",
    "HEARTBEAT.md",
]


@dataclass(frozen=True)
class LocalMemoryDocument:
    source: str
    item_id: str
    title: str
    text: str

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def load_local_memory_documents(
    openclaw_workspace_path: Path | None = None,
    claude_projects_path: Path | None = None,
    codex_projects_path: Path | None = None,
    claude_project_memory_path: Path | None = None,
    openclaw_sessions_path: Path | None = None,
    claude_global_path: Path | None = None,
) -> list[LocalMemoryDocument]:
    candidates: list[tuple[str, Path]] = []
    candidates.extend(_openclaw_workspace_candidates(openclaw_workspace_path or settings.openclaw_workspace_path))
    candidates.extend(_recursive_candidates("claude_projects", claude_projects_path or settings.claude_projects_path))
    candidates.extend(_recursive_candidates("codex_projects", codex_projects_path or settings.codex_projects_path))
    candidates.extend(_recursive_candidates("claude_project_memory", claude_project_memory_path or settings.claude_project_memory_path))
    candidates.extend(_recursive_candidates("openclaw_sessions", openclaw_sessions_path or settings.openclaw_sessions_path))
    candidates.extend(_file_candidate("claude_global", claude_global_path or settings.claude_global_path))

    docs: list[LocalMemoryDocument] = []
    seen_fingerprints: set[str] = set()
    for source, path in candidates:
        text = _read_text(path)
        if not text:
            continue
        document = LocalMemoryDocument(
            source=source,
            item_id=str(path.expanduser().resolve()),
            title=path.stem,
            text=text,
        )
        if document.fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(document.fingerprint)
        docs.append(document)
    return docs


async def ingest_local_memory_documents(
    documents: list[LocalMemoryDocument],
    memory: CogneeMemory,
    limit: int | None = None,
) -> tuple[int, int]:
    ingested = 0
    failed = 0
    selected = documents if limit is None else documents[:limit]
    for document in selected:
        try:
            sanitized = sanitize_note(document.text)
            if not sanitized.content:
                failed += 1
                continue
            chunks = chunk_text(sanitized.content)
            for index, chunk in enumerate(chunks, start=1):
                chunk_label = f" chunk {index}/{len(chunks)}" if len(chunks) > 1 else ""
                payload = (
                    f"Source: {document.source}:{document.title}{chunk_label}\n"
                    f"Path: {document.item_id}\n\n"
                    f"{chunk}"
                )
                validate_cognee_payload(payload)
                await memory.remember(payload, source=f"{document.source}:{document.item_id}")
            ingested += 1
        except Exception:
            failed += 1
    return ingested, failed


def _openclaw_workspace_candidates(root: Path) -> list[tuple[str, Path]]:
    path = root.expanduser()
    candidates: list[tuple[str, Path]] = []
    for name in OPENCLAW_ROOT_FILES:
        candidates.extend(_file_candidate("openclaw_workspace", path / name))
    candidates.extend(_recursive_candidates("openclaw_workspace_memory", path / "memory"))
    return candidates


def _recursive_candidates(source: str, root: Path) -> list[tuple[str, Path]]:
    path = root.expanduser()
    if not path.exists():
        return []
    if path.is_file():
        return _file_candidate(source, path)
    return sorted(
        (source, child)
        for child in path.rglob("*")
        if child.is_file() and child.suffix.lower() in TEXT_SUFFIXES
    )


def _file_candidate(source: str, path: Path) -> list[tuple[str, Path]]:
    expanded = path.expanduser()
    if expanded.exists() and expanded.is_file() and expanded.suffix.lower() in TEXT_SUFFIXES:
        return [(source, expanded)]
    return []


def _read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        return _read_jsonl_text(path)
    if suffix == ".json":
        return _read_json_text(path)
    return path.read_text(encoding="utf-8", errors="replace").strip()


def _read_json_text(path: Path) -> str:
    try:
        return _json_value_to_text(json.loads(path.read_text(encoding="utf-8", errors="replace"))).strip()
    except json.JSONDecodeError:
        return path.read_text(encoding="utf-8", errors="replace").strip()


def _read_jsonl_text(path: Path) -> str:
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            lines.append(line)
            continue
        text = _json_value_to_text(parsed).strip()
        if text:
            lines.append(text)
    return "\n\n".join(lines).strip()


def _json_value_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n\n".join(item for item in (_json_value_to_text(child).strip() for child in value) if item)
    if not isinstance(value, dict):
        return ""

    role = value.get("role") or value.get("sender") or value.get("author")
    content = (
        value.get("content")
        or value.get("text")
        or value.get("message")
        or value.get("summary")
        or value.get("body")
    )
    if content is not None:
        text = _json_value_to_text(content).strip()
        return f"{role}: {text}" if role and text else text

    preferred: list[str] = []
    for key in ("title", "name", "type", "created_at"):
        if value.get(key):
            preferred.append(f"{key}: {value[key]}")
    nested = [
        _json_value_to_text(child).strip()
        for key, child in value.items()
        if key not in {"id", "uuid", "created_at", "updated_at"}
    ]
    preferred.extend(item for item in nested if item)
    return "\n".join(preferred)


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Import local curated memory files into Cognee.")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    memory = CogneeMemory(max_items=settings.max_context_items)
    docs = load_local_memory_documents()
    ingested, failed = await ingest_local_memory_documents(docs, memory, args.limit)
    print(f"Ingested {ingested} local memory documents. Failed: {failed}.")


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
