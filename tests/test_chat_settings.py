from app.storage import ChatSettingsStore, connect, init_db


def test_chat_settings_skill_lifecycle(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        store = ChatSettingsStore(conn)

        assert store.get("123").skill_name is None

        store.set_skill("123", "research")
        assert store.get("123").skill_name == "research"

        store.set_skill("123", None)
        assert store.get("123").skill_name is None
