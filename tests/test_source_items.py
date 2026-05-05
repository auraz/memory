from app.storage import SourceItemStore, connect, init_db


def test_source_item_store_lifecycle(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        store = SourceItemStore(conn)

        assert not store.is_terminal("chatgpt", "1", "abc")

        store.mark("chatgpt", "1", "abc", "completed")
        assert store.is_terminal("chatgpt", "1", "abc")
        assert store.count("chatgpt") == 1
        assert store.count("chatgpt", "completed") == 1
        record = store.get("chatgpt", "1")
        assert record is not None
        assert record.content_text == ""

        assert not store.is_terminal("chatgpt", "1", "changed")


def test_source_item_store_tracks_content_and_stat_metadata(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        store = SourceItemStore(conn)
        store.mark(
            "local",
            "file.md",
            "abc",
            "completed",
            content_text="old text",
            size_bytes=10,
            mtime_ns=20,
        )

        record = store.get("local", "file.md")

    assert record is not None
    assert record.content_text == "old text"
    assert record.size_bytes == 10
    assert record.mtime_ns == 20
