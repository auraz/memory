from app.memory.local_sources import (
    LocalMemoryDocument,
    _is_context_overflow_error,
    _is_unsupported_language_error,
    _json_value_to_text,
    _summary_chunks,
    added_text_delta,
    is_unchanged_by_stat,
    load_local_memory_documents,
    should_ingest_delta,
)


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
    codex_projects.joinpath("project-summary.json").write_text(
        '{"memory":"codex project summary"}',
        encoding="utf-8",
    )
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
    assert "codex project summary" in texts
    assert "codex session" not in texts
    assert "openclaw session" in texts
    assert "global instructions" in texts


def test_added_text_delta_only_returns_new_lines():
    delta = added_text_delta("a\nb\nc", "a\nb\nnew\nc\nalso new")

    assert delta == "new\nalso new"


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
    assert not should_ingest_delta(document)


def test_jsonl_files_are_not_local_memory_sources(tmp_path):
    codex_projects = tmp_path / "codex" / "projects"
    codex_projects.mkdir(parents=True)
    codex_projects.joinpath("session.jsonl").write_text(
        '{"role":"user","content":"raw session should not import"}\n',
        encoding="utf-8",
    )

    docs = load_local_memory_documents(
        openclaw_workspace_path=tmp_path / "missing-openclaw",
        claude_projects_path=tmp_path / "missing-claude",
        codex_projects_path=codex_projects,
        claude_project_memory_path=tmp_path / "missing-memory",
        openclaw_sessions_path=tmp_path / "missing-sessions",
        claude_global_path=tmp_path / "missing-global.md",
    )

    assert docs == []


def test_summary_chunks_can_include_all_chunks():
    text = "a" * 2500

    chunks = _summary_chunks(text, chunk_chars=1000, max_chunks=0)

    assert [len(chunk) for chunk in chunks] == [1000, 1000, 500]


def test_summary_chunks_caps_head_and_tail():
    chunks = _summary_chunks("a" * 1000 + "b" * 1000 + "c" * 1000 + "d" * 1000 + "e" * 1000 + "f" * 1000, chunk_chars=1000, max_chunks=4)

    assert chunks == ["a" * 1000, "b" * 1000, "e" * 1000, "f" * 1000]


def test_apfel_error_classifiers():
    assert _is_unsupported_language_error("Unsupported language or locale was used")
    assert _is_context_overflow_error("Input exceeds the 4096-token context window")


def test_json_value_to_text_extracts_nested_content():
    assert _json_value_to_text({"role": "user", "content": "hello"}) == "user: hello"
    assert _json_value_to_text({"summary": {"text": "compact"}}) == "compact"
