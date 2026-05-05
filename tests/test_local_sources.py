import asyncio

from app.memory.local_sources import ingest_local_memory_documents, load_local_memory_documents


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
