import asyncio

from app.memory.cognee_store import MemoryItem
from app.memory.palace import (
    GENERATED_BEGIN,
    PalaceRoomSpec,
    build_palace,
    collect_room_context,
    extract_generated_content,
    extract_manual_content,
    render_room,
    strip_memory_markers,
)


class FakeMemory:
    def __init__(self):
        self.remembered = []

    async def safe_recall(self, query):
        return [MemoryItem(text=f"memory for {query}", source="test")], None

    async def remember(self, text, source=None):
        self.remembered.append((text, source))


class FakeProvider:
    def __init__(self):
        self.calls = []

    async def complete(self, system, user):
        self.calls.append((system, user))
        return "## Identity\n- Draft fact [M1]\n\n## Evidence\n- [M1] test"


def test_collect_room_context_includes_recalled_items():
    room = PalaceRoomSpec(
        name="test",
        filename="test.md",
        title="Test",
        recall_queries=("query one",),
        sections=("Evidence",),
    )

    context = asyncio.run(collect_room_context(FakeMemory(), room))

    assert "Query: query one" in context
    assert "[M1 source=test]" in context
    assert "memory for query one" in context


def test_build_palace_writes_room_files_and_can_ingest(tmp_path):
    memory = FakeMemory()
    provider = FakeProvider()

    paths = asyncio.run(build_palace(memory=memory, provider=provider, output_dir=tmp_path, ingest=True))

    assert len(paths) == 5
    about = tmp_path / "about_me.md"
    assert about.exists()
    text = about.read_text(encoding="utf-8")
    assert "# About Me" in text
    assert "Status: draft" in text
    assert "Draft fact" in text
    assert "[M1]" not in text
    assert memory.remembered
    assert memory.remembered[0][1] == "palace:about_me"


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


def test_build_palace_evolves_existing_room(tmp_path):
    existing = (
        "# About Me\n\n"
        "Manual note.\n\n"
        f"{GENERATED_BEGIN}\nGenerated: old\nStatus: draft\nSource: Frakir palace-build\n\n"
        "## Identity\n- old generated fact\n<!-- FRAKIR:END generated -->\n"
    )
    (tmp_path / "about_me.md").write_text(existing, encoding="utf-8")
    memory = FakeMemory()
    provider = FakeProvider()

    asyncio.run(build_palace(memory=memory, provider=provider, output_dir=tmp_path))

    assert provider.calls
    _system, user = provider.calls[0]
    assert "old generated fact" in user
    assert "Manual note." in user
    rendered = (tmp_path / "about_me.md").read_text(encoding="utf-8")
    assert "Manual note." in rendered
    assert "Draft fact" in rendered
    assert "[M1]" not in rendered


def test_strip_memory_markers_removes_source_labels():
    text = "## Identity\n- Draft fact [M1]\n\nSources: [M1]\n- Another fact [M2 source=test]"

    stripped = strip_memory_markers(text)

    assert "[M1]" not in stripped
    assert "[M2 source=test]" not in stripped
    assert "Draft fact" in stripped
    assert "Another fact" in stripped
