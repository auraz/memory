import json
import hashlib

import app.memory.summary_importer as summary_importer
from app.memory.local_sources import LocalMemoryDocument


def test_summary_file_round_trip(tmp_path):
    document = LocalMemoryDocument(
        source="claude_projects",
        item_id="/tmp/session.jsonl",
        title="session",
        text="raw transcript",
    )
    summary_path = summary_importer.summary_path_for_document(document, tmp_path)

    summary_importer.write_summary_file(summary_path, document, "raw transcript", "- durable fact")
    metadata, body = summary_importer.read_summary_file(summary_path)

    assert metadata["source"] == "claude_projects"
    assert metadata["item_id"] == "/tmp/session.jsonl"
    digest = hashlib.sha256("raw transcript".encode("utf-8")).hexdigest()
    assert metadata["fingerprint"] == digest
    assert metadata["sanitized_fingerprint"] == digest
    assert body == "- durable fact"


def test_plan_summary_documents_scores_and_skips(tmp_path):
    existing = LocalMemoryDocument(
        source="claude_projects",
        item_id="/tmp/existing.jsonl",
        title="existing",
        text="decision project plan",
    )
    summary_importer.write_summary_file(
        summary_importer.summary_path_for_document(existing, tmp_path),
        existing,
        existing.text,
        "- already summarized",
    )
    curated = LocalMemoryDocument(
        source="openclaw_workspace",
        item_id="/tmp/MEMORY.md",
        title="MEMORY",
        text="short",
    )
    tiny = LocalMemoryDocument(
        source="claude_projects",
        item_id="/tmp/tiny.jsonl",
        title="tiny",
        text="ok",
    )
    useful = LocalMemoryDocument(
        source="claude_projects",
        item_id="/tmp/useful.jsonl",
        title="useful",
        text="user: important project decision\nassistant: implemented fixed bug\n" * 5,
    )

    plan = summary_importer.plan_summary_documents([existing, curated, tiny, useful], tmp_path)
    by_title = {item.document.title: item for item in plan}

    assert by_title["existing"].status == "existing"
    assert by_title["MEMORY"].status == "process"
    assert by_title["tiny"].status == "skip-tiny"
    assert by_title["useful"].status == "process"
    assert by_title["useful"].score > by_title["tiny"].score


def test_plan_skips_claude_raw_session_when_sessions_index_has_summary(tmp_path):
    raw = tmp_path / "session-1.jsonl"
    raw.write_text('{"role":"user","content":"important project decision"}\n', encoding="utf-8")
    index = tmp_path / "sessions-index.json"
    index.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "sessionId": "session-1",
                        "fullPath": str(raw),
                        "summary": "Compact project decision summary",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    raw_doc = LocalMemoryDocument(
        source="claude_projects",
        item_id=str(raw.resolve()),
        title="session-1",
        text=raw.read_text(encoding="utf-8"),
    )
    index_doc = LocalMemoryDocument(
        source="claude_projects",
        item_id=str(index.resolve()),
        title="sessions-index",
        text=index.read_text(encoding="utf-8"),
    )

    plan = summary_importer.plan_summary_documents([raw_doc, index_doc], tmp_path / "summaries")
    by_title = {item.document.title: item for item in plan}

    assert by_title["session-1"].status == "skip-compact"
