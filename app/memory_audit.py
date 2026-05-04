from app.memory import CogneeMemory
from app.memory.audit import build_memory_audit, render_memory_audit
from app.settings import settings
from app.storage import IngestRunStore, SourceItemStore, connect, init_db


def main() -> None:
    init_db(settings.sqlite_path)
    with connect(settings.sqlite_path) as conn:
        memory = CogneeMemory(max_items=settings.max_context_items)
        audit = build_memory_audit(
            memory=memory,
            ingest_runs=IngestRunStore(conn),
            source_items=SourceItemStore(conn),
        )
        print(render_memory_audit(audit))
