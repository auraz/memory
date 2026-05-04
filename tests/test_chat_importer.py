import json

from app.memory.chat_importer import load_chat_documents


def test_load_chatgpt_conversations_json(tmp_path):
    export = tmp_path / "conversations.json"
    export.write_text(
        json.dumps(
            [
                {
                    "id": "conv-1",
                    "title": "Emotion work",
                    "mapping": {
                        "a": {
                            "message": {
                                "create_time": 1,
                                "author": {"role": "user"},
                                "content": {"parts": ["What did I work on emotions?"]},
                            }
                        },
                        "b": {
                            "message": {
                                "create_time": 2,
                                "author": {"role": "assistant"},
                                "content": {"parts": ["You worked on an emotion atlas."]},
                            }
                        },
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    docs = load_chat_documents("chatgpt", export)

    assert len(docs) == 1
    assert docs[0].source == "chatgpt"
    assert docs[0].item_id == "conv-1"
    assert "user: What did I work on emotions?" in docs[0].text
    assert "assistant: You worked on an emotion atlas." in docs[0].text


def test_load_claude_conversation_json(tmp_path):
    export = tmp_path / "claude.json"
    export.write_text(
        json.dumps(
            {
                "uuid": "claude-1",
                "name": "Planning",
                "chat_messages": [
                    {"sender": "human", "text": "Plan this"},
                    {"sender": "assistant", "text": "First step"},
                ],
            }
        ),
        encoding="utf-8",
    )

    docs = load_chat_documents("claude", export)

    assert len(docs) == 1
    assert docs[0].source == "claude"
    assert docs[0].item_id == "claude-1"
    assert "human: Plan this" in docs[0].text


def test_load_openclaw_markdown(tmp_path):
    export = tmp_path / "openclaw.md"
    export.write_text("# Chat\n\nhello", encoding="utf-8")

    docs = load_chat_documents("openclaw", export)

    assert len(docs) == 1
    assert docs[0].source == "openclaw"
    assert docs[0].text == "# Chat\n\nhello"
