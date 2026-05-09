import argparse
import asyncio
import hashlib
import json
import subprocess
from collections.abc import Awaitable, Callable
from difflib import SequenceMatcher
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.memory.cognee_store import CogneeMemory
from app.memory.obsidian_importer import chunk_text, sanitize_note, validate_cognee_payload
from app.providers.factory import create_provider
from app.runtime_limits import raise_file_descriptor_limit
from app.settings import settings


LOCAL_MEMORY_SOURCE = "local_memory"
TEXT_SUFFIXES = {".md", ".qmd", ".txt", ".json", ".jsonl"}
ProgressCallback = Callable[[str], Awaitable[None]]
OPENCLAW_ROOT_FILES = [
    "IDENTITY.md",
    "SOUL.md",
    "USER.md",
    "TOOLS.md",
    "MEMORY.md",
    "HEARTBEAT.md",
]


class UnsupportedApfelLanguageError(RuntimeError):
    pass


class ApfelContextOverflowError(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalMemoryDocument:
    source: str
    item_id: str
    title: str
    text: str
    size_bytes: int = 0
    mtime_ns: int = 0

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def sanitized_text(self) -> str:
        return sanitize_note(self.text).content


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
            size_bytes=path.stat().st_size,
            mtime_ns=path.stat().st_mtime_ns,
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
    progress: ProgressCallback | None = None,
    errors: list[str] | None = None,
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
            memory_text = await prepare_local_memory_text(document, sanitized.content, progress)
            await index_local_memory_text(document, memory_text, memory, progress)
            ingested += 1
        except Exception as exc:
            if errors is not None:
                errors.append(f"{type(exc).__name__}: {exc}")
            failed += 1
    return ingested, failed


async def ingest_local_memory_delta(
    document: LocalMemoryDocument,
    previous_text: str,
    memory: CogneeMemory,
    progress: ProgressCallback | None = None,
    errors: list[str] | None = None,
) -> tuple[bool, str]:
    current_text = document.sanitized_text
    delta_text = added_text_delta(previous_text, current_text)
    if not delta_text.strip():
        return False, current_text
    delta_document = LocalMemoryDocument(
        source=document.source,
        item_id=document.item_id,
        title=f"{document.title} updates",
        text=delta_text,
        size_bytes=document.size_bytes,
        mtime_ns=document.mtime_ns,
    )
    ingested, _failed = await ingest_local_memory_documents([delta_document], memory, progress=progress, errors=errors)
    return ingested > 0, current_text


async def index_local_memory_text(
    document: LocalMemoryDocument,
    memory_text: str,
    memory: CogneeMemory,
    progress: ProgressCallback | None = None,
) -> None:
    chunks = chunk_text(memory_text)
    if len(chunks) > 1:
        await _notify(progress, f"indexing {len(chunks)} chunk(s)")
    for index, chunk in enumerate(chunks, start=1):
        if len(chunks) > 1:
            await _notify(progress, f"indexing chunk {index}/{len(chunks)}")
        chunk_label = f" chunk {index}/{len(chunks)}" if len(chunks) > 1 else ""
        payload = (
            f"Source: {document.source}:{document.title}{chunk_label}\n"
            f"Path: {document.item_id}\n\n"
            f"{chunk}"
        )
        validate_cognee_payload(payload)
        await memory.remember(payload, source=f"{document.source}:{document.item_id}")


async def prepare_local_memory_text(
    document: LocalMemoryDocument,
    sanitized_text: str,
    progress: ProgressCallback | None = None,
) -> str:
    if should_summarize_with_apfel(document, sanitized_text):
        return await summarize_text_with_apfel(document, sanitized_text, progress)
    return sanitized_text


def should_summarize_with_apfel(document: LocalMemoryDocument, text: str) -> bool:
    sources = {
        source.strip()
        for source in settings.apfel_summary_sources.split(",")
        if source.strip()
    }
    return document.source in sources and len(text) >= settings.apfel_summary_min_chars


async def summarize_text_with_apfel(
    document: LocalMemoryDocument,
    text: str,
    progress: ProgressCallback | None = None,
) -> str:
    chunks = _summary_chunks(text, settings.apfel_summary_chunk_chars, settings.apfel_summary_max_chunks)
    summaries: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        await _notify(progress, f"summarizing with apfel {index}/{len(chunks)}")
        prompt = (
            "Summarize this Claude Code project/session text for long-term personal memory indexing. "
            "Keep durable facts, project names, user preferences, decisions, commands, bugs, outcomes, "
            "and unresolved next steps. Drop raw logs, repeated code, stack traces, and filler. "
            "Do not copy secrets or tokens; replace them with [redacted secret]. "
            f"Return concise Markdown bullets. File: {document.title}. Part {index}/{len(chunks)}."
        )
        summaries.append(await _run_apfel_summary_with_translation(prompt, chunk, progress))
    summary = "\n\n".join(item.strip() for item in summaries if item.strip()).strip()
    if not summary:
        raise RuntimeError("Apfel returned an empty summary")
    return f"Apfel summary of {document.source}:{document.title}\n\n{summary}"


async def summarize_text_with_apfel_rolling(
    document: LocalMemoryDocument,
    text: str,
    progress: ProgressCallback | None = None,
) -> str:
    chunks = _summary_chunks(text, settings.apfel_summary_chunk_chars, 0)
    running_summary = ""
    for index, chunk in enumerate(chunks, start=1):
        await _notify(progress, f"summarizing with apfel {index}/{len(chunks)}")
        prompt = (
            "You maintain a compact long-term memory summary for a personal agent. "
            "Update the existing summary with the new source chunk. Preserve durable facts, user preferences, "
            "project names, decisions, commands, bugs, outcomes, and unresolved next steps. Drop duplicates, "
            "raw logs, repeated code, stack traces, and filler. Redact secrets/tokens as [redacted secret]. "
            f"Keep the updated summary under {settings.apfel_rolling_summary_max_chars} characters. "
            f"Return only concise Markdown bullets. Source: {document.source}:{document.title}."
        )
        input_text = (
            "Existing running summary:\n"
            f"{running_summary or '(none)'}\n\n"
            "New source chunk:\n"
            f"{chunk}"
        )
        running_summary = await _run_apfel_summary_with_translation(prompt, input_text, progress)
        running_summary = running_summary[: settings.apfel_rolling_summary_max_chars].strip()
    if not running_summary:
        raise RuntimeError("Apfel returned an empty rolling summary")
    return f"Apfel rolling summary of {document.source}:{document.title}\n\n{running_summary}"


async def _notify(progress: ProgressCallback | None, stage: str) -> None:
    if progress is not None:
        await progress(stage)


def _summary_chunks(text: str, chunk_chars: int, max_chunks: int) -> list[str]:
    chunk_chars = max(1000, chunk_chars)
    chunks = [text[index : index + chunk_chars] for index in range(0, len(text), chunk_chars)]
    if max_chunks <= 0:
        return chunks
    if len(chunks) <= max_chunks:
        return chunks
    head_count = max_chunks // 2
    tail_count = max_chunks - head_count
    return chunks[:head_count] + chunks[-tail_count:]


async def _run_apfel_summary(prompt: str, text: str) -> str:
    command = [
        settings.apfel_cli_path,
        "-q",
        "--no-color",
        "--context-strategy",
        "summarize",
        "--max-tokens",
        "900",
        prompt,
    ]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Apfel CLI not found: {settings.apfel_cli_path}") from exc

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(text.encode("utf-8")),
            timeout=settings.apfel_summary_timeout_seconds,
        )
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise RuntimeError("Apfel summary timed out") from exc

    if process.returncode != 0:
        error = stderr.decode("utf-8", errors="replace").strip()
        if _is_unsupported_language_error(error):
            raise UnsupportedApfelLanguageError(error or "Unsupported language")
        if _is_context_overflow_error(error):
            raise ApfelContextOverflowError(error or "Context overflow")
        raise RuntimeError(f"Apfel summary failed: {error or f'exit {process.returncode}'}")
    return stdout.decode("utf-8", errors="replace").strip()


async def _run_apfel_summary_with_translation(
    prompt: str,
    text: str,
    progress: ProgressCallback | None = None,
) -> str:
    try:
        return await _run_apfel_summary(prompt, text)
    except ApfelContextOverflowError:
        await _notify(progress, "falling back to LLM summary after apfel context overflow")
        return await _summarize_with_llm(prompt, text)
    except UnsupportedApfelLanguageError as exc:
        if not settings.apfel_translate_unsupported_language:
            raise RuntimeError(f"Apfel summary failed: {exc}") from exc
        await _notify(progress, "translating unsupported language to English")
        translated = await _translate_to_english(text)
        await _notify(progress, "retrying apfel summary in English")
        try:
            return await _run_apfel_summary(prompt, translated)
        except ApfelContextOverflowError:
            await _notify(progress, "falling back to LLM summary after apfel context overflow")
            return await _summarize_with_llm(prompt, translated)
        except UnsupportedApfelLanguageError as retry_exc:
            if not settings.apfel_llm_fallback_on_unsupported_language:
                raise RuntimeError(f"Apfel summary failed after translation: {retry_exc}") from retry_exc
            await _notify(progress, "falling back to LLM summary")
            return await _summarize_with_llm(prompt, translated)


async def _translate_to_english(text: str) -> str:
    provider = create_provider(settings)
    system = (
        "Translate the user's text to English for downstream local summarization. "
        "Preserve names, paths, commands, code identifiers, timestamps, bullets, and factual structure. "
        "Do not summarize. Redact obvious secrets/tokens as [redacted secret]."
    )
    translated = await provider.complete(system, text)
    if not translated.strip():
        raise RuntimeError("Translation returned empty text")
    return translated.strip()


async def _summarize_with_llm(prompt: str, text: str) -> str:
    provider = create_provider(settings)
    system = (
        "You are generating compact English long-term memory notes for a personal agent. "
        "Follow the user's summarization instructions exactly. Return only concise Markdown bullets. "
        "Redact obvious secrets/tokens as [redacted secret]."
    )
    summary = await provider.complete(system, f"{prompt}\n\nSource text:\n{text}")
    if not summary.strip():
        raise RuntimeError("LLM summary fallback returned empty text")
    return summary.strip()


def _is_unsupported_language_error(error: str) -> bool:
    lowered = error.lower()
    return "unsupported language" in lowered or "unsupported language or locale" in lowered


def _is_context_overflow_error(error: str) -> bool:
    lowered = error.lower()
    return "context overflow" in lowered or "context window" in lowered or "input exceeds" in lowered


def added_text_delta(previous_text: str, current_text: str) -> str:
    previous_lines = previous_text.splitlines()
    current_lines = current_text.splitlines()
    matcher = SequenceMatcher(a=previous_lines, b=current_lines, autojunk=False)
    added: list[str] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in {"insert", "replace"}:
            added.extend(line for line in current_lines[j1:j2] if line.strip())
    return "\n".join(added).strip()


def should_ingest_delta(document: LocalMemoryDocument) -> bool:
    path = Path(document.item_id)
    if document.source in {"openclaw_workspace_memory", "openclaw_sessions", "claude_projects", "codex_projects"}:
        return True
    return bool(path.name.startswith("20") and path.suffix.lower() in {".md", ".qmd", ".txt", ".jsonl"})


def is_unchanged_by_stat(document: LocalMemoryDocument, size_bytes: int, mtime_ns: int) -> bool:
    return document.size_bytes == size_bytes and document.mtime_ns == mtime_ns


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

    soft_limit, hard_limit = raise_file_descriptor_limit()
    print(f"Open file limit: soft={soft_limit} hard={hard_limit}", flush=True)
    memory = CogneeMemory(max_items=settings.max_context_items)
    docs = load_local_memory_documents()
    ingested, failed = await ingest_local_memory_documents(docs, memory, args.limit)
    print(f"Ingested {ingested} local memory documents. Failed: {failed}.")


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
