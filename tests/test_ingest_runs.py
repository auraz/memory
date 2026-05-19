from app.storage import IngestRunStore, connect, init_db


def test_ingest_run_store_lifecycle(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        store = IngestRunStore(conn)
        run_id = store.start("vault", 10)
        store.update(run_id, 3, "note.md")

        latest = store.latest()
        assert latest is not None
        assert latest.status == "running"
        assert latest.processed_files == 3
        assert latest.total_files == 10

        store.finish(run_id, "completed", "done")
        latest = store.latest()
        assert latest is not None
        assert latest.status == "completed"
        assert latest.message == "done"


def test_ingest_run_store_tracks_local_memory_source(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        store = IngestRunStore(conn)
        run_id = store.start("local_memories", 1372)
        store.update(run_id, 5, "claude_projects: user_work")

        latest = store.latest()
        assert latest is not None
        assert latest.source == "local_memories"
        assert latest.processed_files == 5
        assert latest.total_files == 1372
        assert latest.message == "claude_projects: user_work"


def test_ingest_file_manifest_tracks_changed_files(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    note = tmp_path / "note.md"
    note.write_text("first", encoding="utf-8")
    init_db(db_path)

    with connect(db_path) as conn:
        store = IngestRunStore(conn)
        run_id = store.start("vault", 1)

        assert not store.is_file_completed(note)

        store.mark_file_completed(note, run_id)
        assert store.is_file_completed(note)
        assert store.is_file_terminal(note)
        assert store.completed_count() == 1

        note.write_text("changed", encoding="utf-8")
        assert not store.is_file_completed(note)
        assert not store.is_file_terminal(note)


def test_clear_manifest(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    note = tmp_path / "note.md"
    note.write_text("first", encoding="utf-8")
    init_db(db_path)

    with connect(db_path) as conn:
        store = IngestRunStore(conn)
        run_id = store.start("vault", 1)
        store.mark_file_completed(note, run_id)

        store.clear_manifest()

        assert store.completed_count() == 0
        assert not store.is_file_completed(note)


def test_abandon_running_marks_interrupted_runs_failed(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        store = IngestRunStore(conn)
        first_id = store.start("vault", 10)
        second_id = store.start("local_memories", 5)
        store.finish(second_id, "completed", "done")

        abandoned = store.abandon_running("Process restarted.")
        rows = conn.execute("select id, status, message, finished_at from ingest_runs order by id").fetchall()

    assert abandoned == 1
    assert rows[0]["id"] == first_id
    assert rows[0]["status"] == "failed"
    assert rows[0]["message"] == "Process restarted."
    assert rows[0]["finished_at"] is not None
    assert rows[1]["status"] == "completed"


def test_failed_file_is_terminal(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    note = tmp_path / "note.md"
    note.write_text("first", encoding="utf-8")
    init_db(db_path)

    with connect(db_path) as conn:
        store = IngestRunStore(conn)
        run_id = store.start("vault", 1)

        store.mark_file_failed(note, run_id, "bad note")

        assert store.is_file_terminal(note)
        assert not store.is_file_completed(note)
        assert store.failed_count() == 1
