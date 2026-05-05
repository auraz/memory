import asyncio

from app.memory.local_sources import (
    LocalMemoryDocument,
    added_text_delta,
    ingest_local_memory_delta,
    ingest_local_memory_documents,
    is_unchanged_by_stat,
    load_local_memory_documents,
    should_ingest_delta,
)


class FakeMemory:
    def __init__(self):
        self.items = []

    async def remember(self, text: str, source: str | None = None):
        self.items.append((text, source))


def test_load_local_memory_documents_from_configured_roots(tmp_path):
    openclaw = tmp_path / "openclaw" / "workspace"
    claude_projects = tmp_path / "claude" / "projects"
    codex_projects = tmp_path / "codex" / "projects"
    claude_memory = claude_projects / "project-a" / "memory"
    sessions = tmp_path / "openclaw" / "sessions"
    global_path = tmp_path / "claude" / "CLAUDE.md"

    (openclaw / "memory").mkdir(parents=True)
    claude_memory.mkdir(parents=True)
    codex_projects.mkdir(parents=True)
    sessions.mkdir(parents=True)
    openclaw.joinpath("IDENTITY.md").write_text("identity", encoding="utf-8")
    openclaw.joinpath("memory", "2026-05-05.md").write_text("daily log", encoding="utf-8")
    claude_memory.joinpath("user_work.md").write_text("user work", encoding="utf-8")
    codex_projects.joinpath("session.jsonl").write_text('{"role":"user","content":"codex session"}\n', encoding="utf-8")
    sessions.joinpath("openclaw-session.md").write_text("openclaw session", encoding="utf-8")
    global_path.write_text("global instructions", encoding="utf-8")

    docs = load_local_memory_documents(
        openclaw_workspace_path=openclaw,
        claude_projects_path=claude_projects,
        codex_projects_path=codex_projects,
        claude_project_memory_path=claude_memory,
        openclaw_sessions_path=sessions,
        claude_global_path=global_path,
    )

    texts = "\n".join(doc.text for doc in docs)
    assert "identity" in texts
    assert "daily log" in texts
    assert "user work" in texts
    assert "user: codex session" in texts
    assert "openclaw session" in texts
    assert "global instructions" in texts


def test_ingest_local_memory_documents(tmp_path):
    memory = FakeMemory()
    source = tmp_path / "MEMORY.md"
    source.write_text("remember this", encoding="utf-8")
    docs = load_local_memory_documents(
        openclaw_workspace_path=tmp_path,
        claude_projects_path=tmp_path / "missing-claude",
        codex_projects_path=tmp_path / "missing-codex",
        claude_project_memory_path=tmp_path / "missing-memory",
        openclaw_sessions_path=tmp_path / "missing-sessions",
        claude_global_path=tmp_path / "missing-global.md",
    )

    ingested, failed = asyncio.run(ingest_local_memory_documents(docs, memory))

    assert ingested == 1
    assert failed == 0
    assert "remember this" in memory.items[0][0]


def test_added_text_delta_only_returns_new_lines():
    delta = added_text_delta("a\nb\nc", "a\nb\nnew\nc\nalso new")

    assert delta == "new\nalso new"


def test_ingest_local_memory_delta_indexes_only_added_text():
    memory = FakeMemory()
    document = LocalMemoryDocument(
        source="openclaw_workspace_memory",
        item_id="/tmp/2026-05-05.md",
        title="2026-05-05",
        text="old line\nnew line",
        size_bytes=18,
        mtime_ns=200,
    )

    done, current_text = asyncio.run(ingest_local_memory_delta(document, "old line", memory))

    assert done is True
    assert current_text == "old line\nnew line"
    assert "new line" in memory.items[0][0]
    assert "old line" not in memory.items[0][0]


def test_local_memory_stat_and_delta_classification():
    document = LocalMemoryDocument(
        source="codex_projects",
        item_id="/tmp/session.jsonl",
        title="session",
        text="hello",
        size_bytes=5,
        mtime_ns=10,
    )

    assert is_unchanged_by_stat(document, 5, 10)
    assert not is_unchanged_by_stat(document, 6, 10)
    assert should_ingest_delta(document)
