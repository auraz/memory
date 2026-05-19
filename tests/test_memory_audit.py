from app.memory.audit import MemoryAudit, ObsidianAudit, SourceAudit, render_memory_audit


def test_render_memory_audit():
    audit = MemoryAudit(
        backend="cognee",
        durable=True,
        storage_path="data/cognee/system",
        obsidian=ObsidianAudit(total=10, completed=3, failed=1, processed=4, pending=6),
        sources=[SourceAudit("chatgpt", configured=False, processed=0, completed=0, failed=0)],
        latest_ingest="#1 completed 3/3 updated 2026-05-17",
        recent_errors=[],
    )

    rendered = render_memory_audit(audit)

    assert "Memory audit" in rendered
    assert "Backend: cognee (durable)" in rendered
    assert "completed: 3" in rendered
    assert "chatgpt: not configured" in rendered
    assert "Recent Cognee errors:\n- none" in rendered
