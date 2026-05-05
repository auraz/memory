import asyncio

from app.agent.service import AgentService
from app.approvals.policy import ApprovalPolicy
from app.memory.cognee_store import MemoryItem
from app.tools.openclaw import OpenClawResult


class FakeProvider:
    def __init__(self):
        self.system = ""
        self.user = ""

    async def complete(self, system: str, user: str) -> str:
        self.system = system
        self.user = user
        return "done"


class FakeMemory:
    async def safe_recall(self, query: str):
        return [MemoryItem(text=f"memory for {query}", source="test")], None


class FakeQueue:
    pass


def test_preview_context_shows_recalled_memory_and_auto_skill(tmp_path):
    agent = AgentService(FakeProvider(), FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), FakeQueue())

    preview = asyncio.run(agent.preview_context("what did I work on emotions?", skill_name="auto"))

    assert preview.selected_skill == "research"
    assert preview.recall_error is None
    assert "[M1] (test) memory for what did I work on emotions?" in preview.context_packet
    assert preview.today_context == "No prior Telegram messages with the bot today."


def test_respond_sends_context_to_provider(tmp_path):
    provider = FakeProvider()
    agent = AgentService(provider, FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), FakeQueue())

    response = asyncio.run(agent.respond("brainstorm ideas", skill_name="auto", today_context="Today with this Telegram chat: hi"))

    assert response == "done"
    assert "Skill: brainstorm" in provider.system
    assert "Today with this Telegram chat: hi" in provider.user
    assert "Relevant long-term memory" in provider.user
    assert "User message:\nbrainstorm ideas" in provider.user


def test_openclaw_task_is_queued_by_default(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    from app.approvals import ApprovalQueue
    from app.storage import connect, init_db

    init_db(db_path)
    with connect(db_path) as conn:
        queue = ApprovalQueue(conn)
        agent = AgentService(FakeProvider(), FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), queue)

        response = asyncio.run(agent.propose_openclaw_task("show recent photos", telegram_chat_id="123"))
        pending = queue.list_pending()

    assert "Queued OpenClaw task #1" in response
    assert pending[0].tool_name == "openclaw.agent_send"
    assert pending[0].payload == {
        "message": "show recent photos",
        "session_id": "frakir-telegram-123",
    }


def test_openclaw_approved_action_runs_tool(tmp_path, monkeypatch):
    db_path = tmp_path / "agent.sqlite"
    from app.approvals.queue import PendingAction
    import app.agent.service as service_module
    from app.approvals import ApprovalQueue
    from app.storage import connect, init_db

    async def fake_run_openclaw_agent(**kwargs):
        return OpenClawResult(text=f"ran {kwargs['message']} in {kwargs['session_id']}", stdout="", stderr="", returncode=0)

    monkeypatch.setattr(service_module, "run_openclaw_agent", fake_run_openclaw_agent)
    init_db(db_path)
    with connect(db_path) as conn:
        queue = ApprovalQueue(conn)
        agent = AgentService(FakeProvider(), FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), queue)

        response = asyncio.run(
            agent._execute_approved(
                PendingAction(
                    id=7,
                    tool_name="openclaw.agent_send",
                    payload={"message": "summarize inbox", "session_id": "frakir-telegram-123"},
                    status="pending",
                )
            )
        )

    assert response == "OpenClaw result:\nran summarize inbox in frakir-telegram-123"
