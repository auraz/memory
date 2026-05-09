import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.memory.chat_importer import load_chat_documents
from app.memory.cognee_store import CogneeMemory
from app.memory.local_sources import (
    LocalMemoryDocument,
    index_local_memory_text,
    load_local_memory_documents,
    summarize_text_with_apfel_rolling,
)
from app.memory.obsidian_importer import sanitize_note
from app.runtime_limits import raise_file_descriptor_limit
from app.settings import settings


DEFAULT_SUMMARY_DIR = Path("data/apfel_summaries")
SIGNAL_KEYWORDS = {
    "decision",
    "todo",
    "next",
    "bug",
    "fixed",
    "implemented",
    "preference",
    "remember",
    "project",
    "plan",
    "issue",
    "error",
    "learned",
    "important",
    "follow up",
}
NOISE_KEYWORDS = {
    "traceback",
    "stack trace",
    "node_modules",
    "package-lock",
    "pnpm-lock",
    "tool_result",
    "tool_use",
    "stdout",
    "stderr",
    "diff --git",
}
CURATED_SOURCES = {"openclaw_workspace", "claude_project_memory", "claude_global"}


@dataclass(frozen=True)
class SummaryFile:
    path: Path
    source: str
    item_id: str
    title: str
    fingerprint: str
    text: str


@dataclass(frozen=True)
class SummaryPlanItem:
    document: LocalMemoryDocument
    summary_path: Path
    score: int
    status: str
    reason: str

    @property
    def should_process(self) -> bool:
        return self.status == "process"


def load_non_obsidian_documents() -> list[LocalMemoryDocument]:
    docs = list(load_local_memory_documents())
    for source in ("chatgpt", "claude", "openclaw"):
        export_path = _source_path(source)
        if export_path is None:
            continue
        for chat_doc in load_chat_documents(source, export_path):
            docs.append(
                LocalMemoryDocument(
                    source=chat_doc.source,
                    item_id=chat_doc.item_id,
                    title=chat_doc.title,
                    text=chat_doc.text,
                )
            )
    return docs


async def write_apfel_summaries(
    documents: list[LocalMemoryDocument],
    output_dir: Path = DEFAULT_SUMMARY_DIR,
    limit: int | None = None,
    only_worthwhile: bool = True,
    include_subagents: bool = False,
) -> tuple[int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    planned = plan_summary_documents(documents, output_dir, include_subagents=include_subagents)
    candidates = [item.document for item in planned if not only_worthwhile or item.should_process]
    selected = candidates if limit is None else candidates[:limit]
    written = 0
    failed = 0
    for index, document in enumerate(selected, start=1):
        summary_path = summary_path_for_document(document, output_dir)
        if summary_path.exists():
            print(f"[{index}/{len(selected)}] skip existing {document.source}:{document.title}", flush=True)
            continue
        try:
            sanitized = sanitize_note(document.text).content
            if not sanitized:
                failed += 1
                print(f"[{index}/{len(selected)}] empty {document.source}:{document.title}", flush=True)
                continue

            async def progress(stage: str) -> None:
                print(f"[{index}/{len(selected)}] {document.source}:{document.title} - {stage}", flush=True)

            summary = await summarize_text_with_apfel_rolling(document, sanitized, progress=progress)
            write_summary_file(summary_path, document, sanitized, summary)
            written += 1
            print(f"[{index}/{len(selected)}] wrote {summary_path}", flush=True)
        except Exception as exc:
            failed += 1
            error_path = summary_path.with_suffix(".error")
            error_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
            print(f"[{index}/{len(selected)}] failed {document.source}:{document.title}: {exc}", flush=True)
    return written, failed


def plan_summary_documents(
    documents: list[LocalMemoryDocument],
    output_dir: Path = DEFAULT_SUMMARY_DIR,
    include_subagents: bool = False,
) -> list[SummaryPlanItem]:
    compact_paths = compact_claude_session_paths(documents)
    return [
        score_summary_document(document, output_dir, compact_paths, include_subagents=include_subagents)
        for document in documents
    ]


def score_summary_document(
    document: LocalMemoryDocument,
    output_dir: Path = DEFAULT_SUMMARY_DIR,
    compact_paths: set[str] | None = None,
    include_subagents: bool = False,
) -> SummaryPlanItem:
    summary_path = summary_path_for_document(document, output_dir)
    if summary_path.exists():
        return SummaryPlanItem(document, summary_path, 0, "existing", "summary already exists")
    if is_claude_subagent_document(document) and not include_subagents:
        return SummaryPlanItem(document, summary_path, 0, "skip-subagent", "Claude subagent transcript; opt in with --include-subagents")
    if has_compact_claude_representation(document, compact_paths or set()):
        return SummaryPlanItem(document, summary_path, 0, "skip-compact", "covered by sessions-index.json")

    text = sanitize_note(document.text).content
    if not text:
        return SummaryPlanItem(document, summary_path, 0, "skip-empty", "empty after sanitization")

    lowered = text.lower()
    char_count = len(text)
    signal_hits = sum(1 for keyword in SIGNAL_KEYWORDS if keyword in lowered)
    noise_hits = sum(1 for keyword in NOISE_KEYWORDS if keyword in lowered)
    role_hits = lowered.count("user:") + lowered.count("assistant:") + lowered.count('"role"')

    if document.source in CURATED_SOURCES:
        score = 100 + signal_hits * 5
        return SummaryPlanItem(document, summary_path, score, "process", "curated source")

    if char_count < 500 and signal_hits == 0:
        return SummaryPlanItem(document, summary_path, 5, "skip-tiny", "tiny with no signal keywords")

    score = 0
    score += min(35, signal_hits * 7)
    score += min(20, role_hits)
    score += min(20, char_count // 5000)
    score -= min(30, noise_hits * 6)
    if document.mtime_ns:
        score += 5
    if document.source in {"claude_projects", "codex_projects", "openclaw_sessions"}:
        score += 10

    if score < 15:
        return SummaryPlanItem(document, summary_path, score, "skip-low-signal", "low signal/noise score")
    return SummaryPlanItem(document, summary_path, score, "process", _score_reason(signal_hits, role_hits, noise_hits))


def compact_claude_session_paths(documents: list[LocalMemoryDocument]) -> set[str]:
    covered: set[str] = set()
    for document in documents:
        path = Path(document.item_id)
        if document.source != "claude_projects" or path.name != "sessions-index.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            full_path = entry.get("fullPath")
            summary = entry.get("summary")
            if isinstance(full_path, str) and isinstance(summary, str) and summary.strip():
                covered.add(str(Path(full_path).expanduser().resolve()))
    return covered


def has_compact_claude_representation(document: LocalMemoryDocument, compact_paths: set[str]) -> bool:
    if document.source != "claude_projects":
        return False
    path = Path(document.item_id)
    if str(path) in compact_paths:
        return True
    if is_claude_subagent_document(document):
        session_dir = path.parent.parent
        parent_session_path = session_dir.parent / f"{session_dir.name}.jsonl"
        return str(parent_session_path.resolve()) in compact_paths
    return False


def is_claude_subagent_document(document: LocalMemoryDocument) -> bool:
    path = Path(document.item_id)
    return document.source == "claude_projects" and path.suffix == ".jsonl" and path.parent.name == "subagents"


def render_summary_plan(items: list[SummaryPlanItem], top: int = 20) -> str:
    total = len(items)
    existing = sum(1 for item in items if item.status == "existing")
    process = sum(1 for item in items if item.status == "process")
    skipped = total - existing - process
    lines = [
        f"Total discovered: {total}",
        f"Already summarized: {existing}",
        f"Will summarize: {process}",
        f"Will skip: {skipped}",
        "",
        "Skip reasons:",
    ]
    reasons: dict[str, int] = {}
    for item in items:
        if item.status.startswith("skip"):
            reasons[item.status] = reasons.get(item.status, 0) + 1
    if reasons:
        lines.extend(f"- {reason}: {count}" for reason, count in sorted(reasons.items()))
    else:
        lines.append("- none")

    candidates = sorted((item for item in items if item.status == "process"), key=lambda item: item.score, reverse=True)
    lines.extend(["", "Top candidates:"])
    if not candidates:
        lines.append("- none")
    for item in candidates[:top]:
        lines.append(
            f"- {item.document.source}:{item.document.title} "
            f"score {item.score} {item.reason}"
        )
    return "\n".join(lines)


def _score_reason(signal_hits: int, role_hits: int, noise_hits: int) -> str:
    parts = []
    if signal_hits:
        parts.append(f"signals={signal_hits}")
    if role_hits:
        parts.append(f"roles={role_hits}")
    if noise_hits:
        parts.append(f"noise={noise_hits}")
    return ", ".join(parts) if parts else "general source signal"


async def ingest_apfel_summary_files(
    summary_dir: Path = DEFAULT_SUMMARY_DIR,
    memory: CogneeMemory | None = None,
    limit: int | None = None,
) -> tuple[int, int]:
    memory = memory or CogneeMemory(max_items=settings.max_context_items)
    summaries = load_summary_files(summary_dir)
    selected = summaries if limit is None else summaries[:limit]
    ingested = 0
    failed = 0
    for index, summary in enumerate(selected, start=1):
        try:
            document = LocalMemoryDocument(
                source=summary.source,
                item_id=summary.item_id,
                title=summary.title,
                text=summary.text,
            )
            print(f"[{index}/{len(selected)}] indexing {summary.source}:{summary.title}", flush=True)
            await index_local_memory_text(document, summary.text, memory)
            ingested += 1
        except Exception as exc:
            failed += 1
            print(f"[{index}/{len(selected)}] failed {summary.path}: {type(exc).__name__}: {exc}", flush=True)
    return ingested, failed


def load_summary_files(summary_dir: Path = DEFAULT_SUMMARY_DIR) -> list[SummaryFile]:
    root = summary_dir.expanduser()
    files: list[SummaryFile] = []
    if not root.exists():
        return files
    for path in sorted(root.glob("*.md")):
        metadata, body = read_summary_file(path)
        files.append(
            SummaryFile(
                path=path,
                source=str(metadata.get("source") or "apfel_summary"),
                item_id=str(metadata.get("item_id") or path.resolve()),
                title=str(metadata.get("title") or path.stem),
                fingerprint=str(metadata.get("fingerprint") or hashlib.sha256(body.encode("utf-8")).hexdigest()),
                text=body,
            )
        )
    return files


def write_summary_file(path: Path, document: LocalMemoryDocument, sanitized_text: str, summary: str) -> None:
    metadata = {
        "source": document.source,
        "item_id": document.item_id,
        "title": document.title,
        "fingerprint": hashlib.sha256(document.text.encode("utf-8")).hexdigest(),
        "sanitized_fingerprint": hashlib.sha256(sanitized_text.encode("utf-8")).hexdigest(),
        "size_bytes": document.size_bytes,
        "mtime_ns": document.mtime_ns,
    }
    frontmatter = yaml.safe_dump(metadata, sort_keys=True, allow_unicode=False).strip()
    path.write_text(f"---\n{frontmatter}\n---\n\n{summary.strip()}\n", encoding="utf-8")


def read_summary_file(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        return {}, text.strip()
    try:
        _start, rest = text.split("---\n", 1)
        metadata_text, body = rest.split("\n---\n", 1)
    except ValueError:
        return {}, text.strip()
    metadata = yaml.safe_load(metadata_text) or {}
    return metadata, body.strip()


def summary_path_for_document(document: LocalMemoryDocument, output_dir: Path) -> Path:
    digest = hashlib.sha256(f"{document.source}:{document.item_id}".encode("utf-8")).hexdigest()[:16]
    safe_title = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in document.title).strip("-")
    safe_title = safe_title[:80] or "untitled"
    return output_dir / f"{document.source}-{safe_title}-{digest}.md"


def _source_path(source: str) -> Path | None:
    if source == "chatgpt":
        return settings.chatgpt_export_path
    if source == "claude":
        return settings.claude_export_path
    if source == "openclaw":
        return settings.openclaw_export_path
    return None


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Generate or ingest Apfel summaries for non-Obsidian sources.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    summarize = subparsers.add_parser("summarize", help="Write worthwhile Apfel summary files without touching Cognee.")
    summarize.add_argument("--limit", type=int, default=None)
    summarize.add_argument("--output", type=Path, default=DEFAULT_SUMMARY_DIR)
    summarize.add_argument("--all-candidates", action="store_true")
    summarize.add_argument("--include-subagents", action="store_true")

    plan = subparsers.add_parser("plan", help="Score non-Obsidian inputs without Apfel or Cognee.")
    plan.add_argument("--output", type=Path, default=DEFAULT_SUMMARY_DIR)
    plan.add_argument("--top", type=int, default=20)
    plan.add_argument("--include-subagents", action="store_true")

    ingest = subparsers.add_parser("ingest", help="Ingest generated Apfel summary files into Cognee.")
    ingest.add_argument("--limit", type=int, default=None)
    ingest.add_argument("--input", type=Path, default=DEFAULT_SUMMARY_DIR)

    args = parser.parse_args()
    if args.command == "summarize":
        docs = load_non_obsidian_documents()
        written, failed = await write_apfel_summaries(
            docs,
            args.output,
            args.limit,
            only_worthwhile=not args.all_candidates,
            include_subagents=args.include_subagents,
        )
        print(f"Summary generation complete. Written: {written}. Failed: {failed}. Output: {args.output}")
        return
    if args.command == "plan":
        docs = load_non_obsidian_documents()
        print(render_summary_plan(plan_summary_documents(docs, args.output, include_subagents=args.include_subagents), top=args.top))
        return
    if args.command == "ingest":
        soft_limit, hard_limit = raise_file_descriptor_limit()
        print(f"Open file limit: soft={soft_limit} hard={hard_limit}", flush=True)
        ingested, failed = await ingest_apfel_summary_files(args.input, limit=args.limit)
        print(f"Summary ingest complete. Ingested: {ingested}. Failed: {failed}.")


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
