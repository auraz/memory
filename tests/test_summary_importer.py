import asyncio
import json

import app.memory.summary_importer as summary_importer
from app.memory.local_sources import LocalMemoryDocument


class FakeMemory:
    def __init__(self):
        self.items = []

    async def remember(self, text: str, source: str | None = None):
        self.items.append((text, source))


def test_write_apfel_summaries_without_cognee(tmp_path, monkeypatch):
    document = LocalMemoryDocument(
        source="claude_projects",
        item_id="/tmp/session.jsonl",
        title="session",
        text="raw transcript",
    )

    async def fake_summary(doc, text, progress=None):
        assert doc == document
        assert text == "raw transcript"
        if progress is not None:
            await progress("summarizing with apfel 1/1")
        return "Apfel rolling summary\n\n- durable fact"

    monkeypatch.setattr(summary_importer, "summarize_text_with_apfel_rolling", fake_summary)

    written, failed = asyncio.run(
        summary_importer.write_apfel_summaries([document], tmp_path, only_worthwhile=False)
    )

    files = list(tmp_path.glob("*.md"))
    assert written == 1
    assert failed == 0
    assert len(files) == 1
    metadata, body = summary_importer.read_summary_file(files[0])
    assert metadata["source"] == "claude_projects"
    assert metadata["item_id"] == "/tmp/session.jsonl"
    assert "- durable fact" in body


def test_ingest_apfel_summary_files_indexes_only_summary(tmp_path):
    document = LocalMemoryDocument(
        source="claude_projects",
        item_id="/tmp/session.jsonl",
        title="session",
        text="raw transcript",
    )
    summary_path = summary_importer.summary_path_for_document(document, tmp_path)
    summary_importer.write_summary_file(summary_path, document, "raw transcript", "- durable fact")
    memory = FakeMemory()

    ingested, failed = asyncio.run(summary_importer.ingest_apfel_summary_files(tmp_path, memory=memory))

    assert ingested == 1
    assert failed == 0
    assert "- durable fact" in memory.items[0][0]
    assert "raw transcript" not in memory.items[0][0]


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


def test_write_apfel_summaries_defaults_to_only_worthwhile(tmp_path, monkeypatch):
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
    summarized = []

    async def fake_summary(doc, text, progress=None):
        summarized.append(doc.title)
        return f"- summary for {doc.title}"

    monkeypatch.setattr(summary_importer, "summarize_text_with_apfel_rolling", fake_summary)

    written, failed = asyncio.run(summary_importer.write_apfel_summaries([tiny, useful], tmp_path))

    assert written == 1
    assert failed == 0
    assert summarized == ["useful"]


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
    assert by_title["sessions-index"].status == "process"


def test_plan_skips_claude_subagent_when_parent_session_index_has_summary(tmp_path):
    parent_raw = tmp_path / "session-1.jsonl"
    parent_raw.write_text('{"role":"user","content":"parent session"}\n', encoding="utf-8")
    subagent = tmp_path / "session-1" / "subagents" / "agent-a1.jsonl"
    subagent.parent.mkdir(parents=True)
    subagent.write_text('{"role":"user","content":"subagent implementation"}\n', encoding="utf-8")
    index = tmp_path / "sessions-index.json"
    index.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "sessionId": "session-1",
                        "fullPath": str(parent_raw),
                        "summary": "Compact parent session summary",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    subagent_doc = LocalMemoryDocument(
        source="claude_projects",
        item_id=str(subagent.resolve()),
        title="agent-a1",
        text=subagent.read_text(encoding="utf-8"),
    )
    index_doc = LocalMemoryDocument(
        source="claude_projects",
        item_id=str(index.resolve()),
        title="sessions-index",
        text=index.read_text(encoding="utf-8"),
    )

    plan = summary_importer.plan_summary_documents(
        [subagent_doc, index_doc],
        tmp_path / "summaries",
        include_subagents=True,
    )
    by_title = {item.document.title: item for item in plan}

    assert by_title["agent-a1"].status == "skip-compact"
    assert by_title["sessions-index"].status == "process"


def test_plan_skips_claude_subagents_by_default(tmp_path):
    subagent = tmp_path / "session-1" / "subagents" / "agent-a1.jsonl"
    subagent.parent.mkdir(parents=True)
    subagent.write_text('{"role":"user","content":"important project decision"}\n', encoding="utf-8")
    doc = LocalMemoryDocument(
        source="claude_projects",
        item_id=str(subagent.resolve()),
        title="agent-a1",
        text=subagent.read_text(encoding="utf-8"),
    )

    default_plan = summary_importer.plan_summary_documents([doc], tmp_path / "summaries")
    included_plan = summary_importer.plan_summary_documents([doc], tmp_path / "summaries", include_subagents=True)

    assert default_plan[0].status == "skip-subagent"
    assert included_plan[0].status == "process"
