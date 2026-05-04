from app.storage import ChatEventStore, connect, init_db


def test_chat_events_today_context(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        store = ChatEventStore(conn)
        store.append("chat-1", "user", "hello", local_date="2026-05-04")
        store.append("chat-1", "assistant", "hi there", local_date="2026-05-04")
        store.append("chat-2", "user", "other chat", local_date="2026-05-04")

        context = store.today_context("chat-1", local_date="2026-05-04")

    assert "Today with this Telegram chat" in context
    assert "User: hello" in context
    assert "Bot: hi there" in context
    assert "other chat" not in context


def test_chat_events_empty_today_context(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        store = ChatEventStore(conn)

        context = store.today_context("chat-1", local_date="2026-05-04")

    assert context == "No prior Telegram messages with the bot today."
