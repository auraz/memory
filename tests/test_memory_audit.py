from app.memory.audit import build_memory_audit, render_memory_audit
from app.storage import IngestRunStore, SourceItemStore, connect, init_db


class FakeMemory:
    backend_name = "fake"
    is_durable = True
    storage_path = "data/cognee/system"


def test_render_memory_audit(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    note = tmp_path / "note.md"
    note.write_text("hello", encoding="utf-8")
    init_db(db_path)

    with connect(db_path) as conn:
        ingest_runs = IngestRunStore(conn)
        source_items = SourceItemStore(conn)
        run_id = ingest_runs.start("vault", 1)
        ingest_runs.mark_file_completed(note, run_id)
        ingest_runs.finish(run_id, "completed", "done")
        source_items.mark("chatgpt", "1", "abc", "completed")

        audit = build_memory_audit(FakeMemory(), ingest_runs, source_items)
        rendered = render_memory_audit(audit)

    assert "Memory audit" in rendered
    assert "Backend: fake (durable)" in rendered
    assert "completed: 1" in rendered
    assert "chatgpt" in rendered
