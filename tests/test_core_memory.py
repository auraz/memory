import asyncio

from app.agent.core_memory import CoreMemoryBlock, SQLiteCoreMemory, normalize_block_label, render_core_memory
from app.agent.core_memory_seed import load_palace_rooms
from app.agent.core_memory_updater import parse_core_memory_updates, should_consider_core_memory_update
from app.agent.service import AgentService
from app.approvals.policy import ApprovalPolicy
from app.memory.palace import GENERATED_BEGIN, GENERATED_END
from app.storage import connect, init_db


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


def test_agent_goal_lifecycle_uses_core_memory(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)
    with connect(db_path) as conn:
        core = SQLiteCoreMemory(conn)
        agent = AgentService(None, None, ApprovalPolicy(tmp_path / "approvals.yaml"), None, core)  # type: ignore[arg-type]

        set_response = asyncio.run(agent.set_goal("  Build Frakir with OpenClaw tools.  "))
        rendered = asyncio.run(agent.render_goal())
        clear_response = asyncio.run(agent.clear_goal())

    assert set_response == "Active goal set:\nBuild Frakir with OpenClaw tools."
    assert rendered == "Active goal:\nBuild Frakir with OpenClaw tools."
    assert clear_response == "Active goal cleared."


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


def test_load_palace_rooms_reads_generated_block(tmp_path):
    palace = tmp_path / "palace"
    palace.mkdir()
    (palace / "about_me.md").write_text(
        f"# About Me\n\nmanual\n\n{GENERATED_BEGIN}\nGenerated: now\n\nStable user facts.\n{GENERATED_END}\n",
        encoding="utf-8",
    )

    rooms = load_palace_rooms(palace)

    assert rooms["about_me"] == "Stable user facts."
