import asyncio

import app.memory.local_sources as local_sources
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


def test_claude_projects_are_summarized_before_ingest(monkeypatch):
    memory = FakeMemory()
    document = LocalMemoryDocument(
        source="claude_projects",
        item_id="/tmp/session.md",
        title="session",
        text="raw claude transcript " * 20,
    )

    async def fake_summary(doc, text, progress=None):
        assert doc == document
        assert "raw claude transcript" in text
        if progress is not None:
            await progress("summarizing with apfel 1/1")
        return "compact summary"

    monkeypatch.setattr(local_sources.settings, "apfel_summary_sources", "claude_projects")
    monkeypatch.setattr(local_sources.settings, "apfel_summary_min_chars", 10)
    monkeypatch.setattr(local_sources, "summarize_text_with_apfel", fake_summary)

    stages = []

    async def progress(stage):
        stages.append(stage)

    ingested, failed = asyncio.run(ingest_local_memory_documents([document], memory, progress=progress))

    assert ingested == 1
    assert failed == 0
    assert "compact summary" in memory.items[0][0]
    assert "raw claude transcript" not in memory.items[0][0]
    assert "summarizing with apfel 1/1" in stages


def test_small_claude_project_files_skip_apfel_summary(monkeypatch):
    memory = FakeMemory()
    document = LocalMemoryDocument(
        source="claude_projects",
        item_id="/tmp/small.md",
        title="small",
        text="small memory",
    )

    async def fail_summary(_doc, _text, _progress=None):
        raise AssertionError("summary should not run")

    monkeypatch.setattr(local_sources.settings, "apfel_summary_sources", "claude_projects")
    monkeypatch.setattr(local_sources.settings, "apfel_summary_min_chars", 100)
    monkeypatch.setattr(local_sources, "summarize_text_with_apfel", fail_summary)

    ingested, failed = asyncio.run(ingest_local_memory_documents([document], memory))

    assert ingested == 1
    assert failed == 0
    assert "small memory" in memory.items[0][0]


def test_apfel_unsupported_language_translates_then_retries(monkeypatch):
    calls = []

    async def fake_run_apfel(_prompt, text):
        calls.append(text)
        if len(calls) == 1:
            raise local_sources.UnsupportedApfelLanguageError(
                "error: [unsupported language] Unsupported language"
            )
        return "english summary"

    async def fake_translate(text):
        assert "привіт" in text
        return "hello translated"

    monkeypatch.setattr(local_sources.settings, "apfel_translate_unsupported_language", True)
    monkeypatch.setattr(local_sources, "_run_apfel_summary", fake_run_apfel)
    monkeypatch.setattr(local_sources, "_translate_to_english", fake_translate)

    stages = []

    async def progress(stage):
        stages.append(stage)

    result = asyncio.run(
        local_sources._run_apfel_summary_with_translation("summarize", "привіт", progress)
    )

    assert result == "english summary"
    assert calls == ["привіт", "hello translated"]
    assert stages == [
        "translating unsupported language to English",
        "retrying apfel summary in English",
    ]


def test_apfel_unsupported_language_falls_back_to_llm_after_translation(monkeypatch):
    calls = []

    async def fake_run_apfel(_prompt, text):
        calls.append(text)
        raise local_sources.UnsupportedApfelLanguageError(
            "error: [unsupported language] Unsupported language"
        )

    async def fake_translate(text):
        assert "привіт" in text
        return "hello translated"

    async def fake_llm_summary(prompt, text):
        assert prompt == "summarize"
        assert text == "hello translated"
        return "- english memory"

    monkeypatch.setattr(local_sources.settings, "apfel_translate_unsupported_language", True)
    monkeypatch.setattr(local_sources.settings, "apfel_llm_fallback_on_unsupported_language", True)
    monkeypatch.setattr(local_sources, "_run_apfel_summary", fake_run_apfel)
    monkeypatch.setattr(local_sources, "_translate_to_english", fake_translate)
    monkeypatch.setattr(local_sources, "_summarize_with_llm", fake_llm_summary)

    stages = []

    async def progress(stage):
        stages.append(stage)

    result = asyncio.run(
        local_sources._run_apfel_summary_with_translation("summarize", "привіт", progress)
    )

    assert result == "- english memory"
    assert calls == ["привіт", "hello translated"]
    assert stages == [
        "translating unsupported language to English",
        "retrying apfel summary in English",
        "falling back to LLM summary",
    ]


def test_apfel_context_overflow_falls_back_to_llm(monkeypatch):
    async def fake_run_apfel(_prompt, _text):
        raise local_sources.ApfelContextOverflowError(
            "error: [context overflow] Input exceeds the 4096-token context window"
        )

    async def fake_llm_summary(prompt, text):
        assert prompt == "summarize"
        assert text == "long text"
        return "- compact memory"

    monkeypatch.setattr(local_sources, "_run_apfel_summary", fake_run_apfel)
    monkeypatch.setattr(local_sources, "_summarize_with_llm", fake_llm_summary)

    stages = []

    async def progress(stage):
        stages.append(stage)

    result = asyncio.run(
        local_sources._run_apfel_summary_with_translation("summarize", "long text", progress)
    )

    assert result == "- compact memory"
    assert stages == ["falling back to LLM summary after apfel context overflow"]
