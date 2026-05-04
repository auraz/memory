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

        assert not store.is_terminal("chatgpt", "1", "changed")
