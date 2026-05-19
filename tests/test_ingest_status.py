from app.bot.telegram import render_ingest_status
from app.storage import IngestRunStore, SourceItemStore, connect, init_db


def test_render_ingest_status_for_vault(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    note = tmp_path / "note.md"
    note.write_text("hello", encoding="utf-8")
    init_db(db_path)

    with connect(db_path) as conn:
        ingest_runs = IngestRunStore(conn)
        source_items = SourceItemStore(conn)
        run_id = ingest_runs.start("vault", 1)
        ingest_runs.update(run_id, 1, "note.md")
        ingest_runs.mark_file_completed(note, run_id)
        run = ingest_runs.latest()
        assert run is not None

        rendered = render_ingest_status(run, ingest_runs, source_items)

    assert "Source: vault" in rendered
    assert "Completed files: 1" in rendered
    assert "Imported items" not in rendered


def test_render_ingest_status_for_configured_obsidian_path(tmp_path, monkeypatch):
    db_path = tmp_path / "agent.sqlite"
    note = tmp_path / "note.md"
    note.write_text("hello", encoding="utf-8")
    monkeypatch.setattr("app.bot.telegram.settings.obsidian_vault_path", tmp_path)
    init_db(db_path)

    with connect(db_path) as conn:
        ingest_runs = IngestRunStore(conn)
        source_items = SourceItemStore(conn)
        run_id = ingest_runs.start(str(tmp_path), 1)
        ingest_runs.update(run_id, 1, "note.md")
        ingest_runs.mark_file_completed(note, run_id)
        run = ingest_runs.latest()
        assert run is not None

        rendered = render_ingest_status(run, ingest_runs, source_items)

    assert f"Source: {tmp_path}" in rendered
    assert "Completed files: 1" in rendered
    assert "Imported items" not in rendered


def test_render_ingest_status_for_local_memories(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        ingest_runs = IngestRunStore(conn)
        source_items = SourceItemStore(conn)
        ingest_runs.start("local_memories", 2)
        ingest_runs.update(1, 1, "claude_projects: user_work")
        source_items.mark("claude_projects", "/tmp/user_work.md", "abc", "completed")
        source_items.mark("codex_projects", "/tmp/session.jsonl", "def", "failed")
        run = ingest_runs.latest()
        assert run is not None

        rendered = render_ingest_status(run, ingest_runs, source_items)

    assert "Source: local_memories" in rendered
    assert "Imported items: 2" in rendered
    assert "Completed items: 1" in rendered
    assert "Failed items: 1" in rendered
    assert "Completed files" not in rendered


def test_render_ingest_status_for_chat_source(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        ingest_runs = IngestRunStore(conn)
        source_items = SourceItemStore(conn)
        ingest_runs.start("chatgpt", 1)
        source_items.mark("chatgpt", "conversation-1", "abc", "completed")
        run = ingest_runs.latest()
        assert run is not None

        rendered = render_ingest_status(run, ingest_runs, source_items)

    assert "Source: chatgpt" in rendered
    assert "Completed items: 1" in rendered
    assert "Completed files" not in rendered
