import asyncio

from app.agent.core_memory import CoreMemoryBlock, SQLiteCoreMemory, normalize_block_label, render_core_memory
from app.agent.core_memory_seed import load_palace_rooms, seed_core_memory_from_palace, sync_core_memory_from_palace
from app.agent.core_memory_updater import parse_core_memory_updates, should_consider_core_memory_update
from app.agent.letta_adapter import LettaCoreMemory
from app.memory.palace import GENERATED_BEGIN, GENERATED_END
from app.agent.service import AgentService
from app.approvals.policy import ApprovalPolicy
from app.memory.cognee_store import MemoryItem
from app.storage import connect, init_db


class FakeProvider:
    def __init__(self, responses: list[str] | None = None):
        self.user = ""
        self.calls: list[tuple[str, str]] = []
        self.responses = responses or ["done"]

    async def complete(self, system: str, user: str) -> str:
        self.user = user
        self.calls.append((system, user))
        if len(self.calls) <= len(self.responses):
            return self.responses[len(self.calls) - 1]
        return self.responses[-1]


class FakeMemory:
    def __init__(self):
        self.remembered = []

    async def safe_recall(self, query: str):
        return [MemoryItem(text="archive fact about the request", source="archive")], None

    async def remember(self, text: str, source: str | None = None):
        self.remembered.append((text, source))


class FakeQueue:
    pass


def test_sqlite_core_memory_defaults_and_updates(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        core = SQLiteCoreMemory(conn)
        blocks = asyncio.run(core.list_blocks())
        assert {block.label for block in blocks} >= {"human", "persona", "active_projects", "active_goal"}

        asyncio.run(core.set_block("Current Focus", "Keep memory focused."))
        rendered = asyncio.run(core.render(1000))

    assert "<current_focus>" in rendered
    assert "Keep memory focused." in rendered


def test_core_memory_is_sent_before_archive_context(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)
    with connect(db_path) as conn:
        core = SQLiteCoreMemory(conn)
        asyncio.run(core.set_block("human", "User prefers concise focused memory."))
        provider = FakeProvider()
        agent = AgentService(provider, FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), FakeQueue(), core)

        asyncio.run(agent.respond("help with memory quality"))

    assert "Core memory blocks" in provider.user
    assert "User prefers concise focused memory." in provider.user
    assert "Focused long-term memory" in provider.user


def test_agent_goal_lifecycle_uses_core_memory(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)
    with connect(db_path) as conn:
        core = SQLiteCoreMemory(conn)
        agent = AgentService(FakeProvider(), FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), FakeQueue(), core)

        set_response = asyncio.run(agent.set_goal("  Build Frakir with OpenClaw tools.  "))
        rendered = asyncio.run(agent.render_goal())
        clear_response = asyncio.run(agent.clear_goal())

    assert set_response == "Active goal set:\nBuild Frakir with OpenClaw tools."
    assert rendered == "Active goal:\nBuild Frakir with OpenClaw tools."
    assert clear_response == "Active goal cleared."


def test_agent_goal_status_uses_planner_context(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)
    with connect(db_path) as conn:
        core = SQLiteCoreMemory(conn)
        provider = FakeProvider(["Goal status response"])
        agent = AgentService(provider, FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), FakeQueue(), core)

        asyncio.run(agent.set_goal("Reuse OpenClaw as tool runtime."))
        response = asyncio.run(agent.goal_status("goal status", today_context="Today: hi"))

    assert response == "Goal status response"
    assert "Active goal:\nReuse OpenClaw as tool runtime." in provider.user
    assert "next concrete step" in provider.user


def test_normalize_block_label():
    assert normalize_block_label("Current Focus") == "current_focus"


def test_render_core_memory_empty():
    assert render_core_memory([], 1000) == "Core memory blocks are empty."


def test_render_core_memory_sorts_and_caps_blocks():
    rendered = render_core_memory(
        [
            CoreMemoryBlock("active_projects", "", "a" * 2000, 100000),
            CoreMemoryBlock("human", "", "human fact", 100000),
            CoreMemoryBlock("preferences", "", "p" * 2000, 100000),
        ],
        max_chars=2500,
    )

    assert rendered.index("<human>") < rendered.index("<active_projects>")
    assert "human fact" in rendered
    assert "a" * 901 not in rendered
    assert "p" * 901 not in rendered


def test_core_memory_update_parser_accepts_fenced_json():
    raw = '```json\n{"updates": {"preferences": "Prefer focused answers."}}\n```'

    assert parse_core_memory_updates(raw) == {"preferences": "Prefer focused answers."}


def test_core_memory_update_trigger_is_conservative():
    assert should_consider_core_memory_update("I do not like to update it manually")
    assert not should_consider_core_memory_update("what is the status?")


def test_auto_updates_core_memory_from_durable_preference(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)

    with connect(db_path) as conn:
        core = SQLiteCoreMemory(conn)
        provider = FakeProvider(
            [
                "answer",
                '{"updates": {"preferences": "User prefers automatic core-memory updates over manual edits."}}',
            ]
        )
        agent = AgentService(provider, FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), FakeQueue(), core)

        response = asyncio.run(agent.respond("I do not like to update it manually"))
        rendered = asyncio.run(core.render(1000))

    assert response == "answer"
    assert len(provider.calls) == 2
    assert "automatic core-memory updates" in rendered


def test_load_palace_rooms_reads_generated_block(tmp_path):
    palace = tmp_path / "palace"
    palace.mkdir()
    (palace / "about_me.md").write_text(
        f"# About Me\n\nmanual\n\n{GENERATED_BEGIN}\nGenerated: now\n\nStable user facts.\n{GENERATED_END}\n",
        encoding="utf-8",
    )

    rooms = load_palace_rooms(palace)

    assert rooms["about_me"] == "Stable user facts."


def test_seed_core_memory_from_palace_updates_blocks(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    palace = tmp_path / "palace"
    palace.mkdir()
    (palace / "preferences.md").write_text("# Preferences\n\nPrefers focused answers.", encoding="utf-8")
    init_db(db_path)

    with connect(db_path) as conn:
        core = SQLiteCoreMemory(conn)
        provider = FakeProvider(
            [
                '{"updates": {"preferences": "User prefers focused answers from palace."}}',
            ]
        )

        result = asyncio.run(seed_core_memory_from_palace(core, provider, palace))
        rendered = asyncio.run(core.render(1000))

    assert result.updates == {"preferences": "User prefers focused answers from palace."}
    assert "focused answers from palace" in rendered


def test_sync_core_memory_from_palace_preserves_alias(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    palace = tmp_path / "palace"
    palace.mkdir()
    (palace / "open_loops.md").write_text("# Open Loops\n\nFinish memory bridge.", encoding="utf-8")
    init_db(db_path)

    with connect(db_path) as conn:
        core = SQLiteCoreMemory(conn)
        provider = FakeProvider(['{"updates": {"current_focus": "Finish memory bridge."}}'])

        result = asyncio.run(sync_core_memory_from_palace(core, provider, palace))
        rendered = asyncio.run(core.render(1000))

    assert result.updates == {"current_focus": "Finish memory bridge."}
    assert "Finish memory bridge." in rendered
    assert "Sync Frakir Letta/core memory blocks" in provider.user


def test_letta_core_memory_uses_agent_core_memory_rest_api(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            import json

            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout=10):
        calls.append((request.full_url, request.get_method(), request.data))
        if request.get_method() == "GET":
            return FakeResponse([{"label": "human", "value": "User fact.", "limit": 1000}])
        return FakeResponse({"label": "human", "value": "Updated.", "limit": 1000})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    core = LettaCoreMemory("agent-123", base_url="http://letta.local")

    blocks = asyncio.run(core.list_blocks())
    asyncio.run(core.set_block("human", "Updated."))

    assert blocks[0].label == "human"
    assert calls[0][0] == "http://letta.local/v1/agents/agent-123/core-memory/blocks"
    assert calls[1][0] == "http://letta.local/v1/agents/agent-123/core-memory/blocks/human"
    assert calls[1][1] == "PATCH"
    assert b"Updated." in calls[1][2]
