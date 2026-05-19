from app.memory.palace import (
    GENERATED_BEGIN,
    PalaceRoomSpec,
    append_palace_memory,
    extract_generated_content,
    extract_manual_content,
    render_room,
    strip_memory_markers,
)


def test_render_room_marks_draft():
    room = PalaceRoomSpec(
        name="test",
        filename="test.md",
        title="Test Room",
        recall_queries=(),
        sections=(),
    )

    rendered = render_room(room, "## Body")

    assert rendered.startswith("# Test Room")
    assert "Status: draft" in rendered
    assert "## Body" in rendered
    assert GENERATED_BEGIN in rendered


def test_render_room_preserves_manual_content():
    room = PalaceRoomSpec(
        name="test",
        filename="test.md",
        title="Test Room",
        recall_queries=(),
        sections=(),
    )
    existing = (
        "# Test Room\n\n"
        "Manual note before.\n\n"
        f"{GENERATED_BEGIN}\nold generated\n<!-- FRAKIR:END generated -->\n\n"
        "Manual note after.\n"
    )

    rendered = render_room(room, "new generated", existing)

    assert "Manual note before." in rendered
    assert "Manual note after." in rendered
    assert "old generated" not in rendered
    assert "new generated" in rendered


def test_extract_previous_generated_and_manual_content():
    text = (
        "# Room\n\n"
        "Manual intro.\n\n"
        f"{GENERATED_BEGIN}\nGenerated: old\nStatus: draft\nSource: Frakir palace-build\n\n"
        "## Generated\n- old fact\n<!-- FRAKIR:END generated -->\n\n"
        "Manual outro.\n"
    )

    assert "old fact" in extract_generated_content(text)
    manual = extract_manual_content(text)
    assert "Manual intro." in manual
    assert "Manual outro." in manual
    assert "old fact" not in manual


def test_strip_memory_markers_removes_source_labels():
    text = "## Identity\n- Draft fact [M1]\n\nSources: [M1]\n- Another fact [M2 source=test]"

    stripped = strip_memory_markers(text)

    assert "[M1]" not in stripped
    assert "[M2 source=test]" not in stripped
    assert "Draft fact" in stripped
    assert "Another fact" in stripped


def test_append_palace_memory_routes_preferences(tmp_path):
    path = append_palace_memory("remember to my preferences: prefer short direct answers", tmp_path)

    assert path == tmp_path / "preferences.md"
    text = path.read_text(encoding="utf-8")
    assert "# Preferences" in text
    assert "prefer short direct answers" in text
    assert "## Remembered" in text
