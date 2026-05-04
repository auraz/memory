from dataclasses import dataclass
from pathlib import Path

from app.log_watch import latest_log_file
from app.memory.obsidian_importer import iter_markdown_files
from app.settings import settings
from app.storage import IngestRunStore, SourceItemStore


@dataclass(frozen=True)
class ObsidianAudit:
    total: int
    completed: int
    failed: int
    processed: int
    pending: int


@dataclass(frozen=True)
class SourceAudit:
    source: str
    configured: bool
    processed: int
    completed: int
    failed: int


@dataclass(frozen=True)
class MemoryAudit:
    backend: str
    durable: bool
    storage_path: str
    obsidian: ObsidianAudit
    sources: list[SourceAudit]
    latest_ingest: str
    recent_errors: list[str]


def build_memory_audit(memory, ingest_runs: IngestRunStore, source_items: SourceItemStore) -> MemoryAudit:
    obsidian_total = _safe_obsidian_total()
    completed = ingest_runs.completed_count()
    failed = ingest_runs.failed_count()
    processed = ingest_runs.terminal_count()
    latest = ingest_runs.latest()
    latest_text = (
        f"#{latest.id} {latest.status} {latest.processed_files}/{latest.total_files} updated {latest.updated_at}"
        if latest
        else "none"
    )
    return MemoryAudit(
        backend=memory.backend_name,
        durable=memory.is_durable,
        storage_path=memory.storage_path,
        obsidian=ObsidianAudit(
            total=obsidian_total,
            completed=completed,
            failed=failed,
            processed=processed,
            pending=max(obsidian_total - processed, 0),
        ),
        sources=[
            _source_audit("chatgpt", settings.chatgpt_export_path, source_items),
            _source_audit("claude", settings.claude_export_path, source_items),
            _source_audit("openclaw", settings.openclaw_export_path, source_items),
        ],
        latest_ingest=latest_text,
        recent_errors=recent_cognee_errors(limit=5),
    )


def render_memory_audit(audit: MemoryAudit) -> str:
    durable = "durable" if audit.durable else "not durable"
    lines = [
        "Memory audit",
        f"Backend: {audit.backend} ({durable})",
        f"Storage: {audit.storage_path}",
        "",
        "Obsidian:",
        f"- total: {audit.obsidian.total}",
        f"- completed: {audit.obsidian.completed}",
        f"- failed: {audit.obsidian.failed}",
        f"- processed: {audit.obsidian.processed}",
        f"- pending: {audit.obsidian.pending}",
        "",
        "Chat sources:",
    ]
    for source in audit.sources:
        configured = "configured" if source.configured else "not configured"
        lines.append(
            f"- {source.source}: {configured}, processed {source.processed}, "
            f"completed {source.completed}, failed {source.failed}"
        )
    lines.extend(["", f"Latest ingest: {audit.latest_ingest}", "", "Recent Cognee errors:"])
    if audit.recent_errors:
        lines.extend(f"- {line}" for line in audit.recent_errors)
    else:
        lines.append("- none")
    return "\n".join(lines)


def recent_cognee_errors(limit: int = 5) -> list[str]:
    latest = latest_log_file(Path("data/cognee/logs"))
    if latest is None:
        return []
    lines = latest.read_text(encoding="utf-8", errors="replace").splitlines()
    matches = [
        line.strip()
        for line in lines
        if any(term in line.lower() for term in ["error", "exception", "traceback", "failed", "runtimeerror"])
    ]
    return matches[-limit:]


def _safe_obsidian_total() -> int:
    try:
        return len(iter_markdown_files(settings.obsidian_vault_path))
    except Exception:
        return 0


def _source_audit(source: str, path: Path | None, source_items: SourceItemStore) -> SourceAudit:
    return SourceAudit(
        source=source,
        configured=bool(path),
        processed=source_items.count(source),
        completed=source_items.count(source, "completed"),
        failed=source_items.count(source, "failed"),
    )
