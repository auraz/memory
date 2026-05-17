import asyncio

from app.agent.service import AgentService, prepare_openclaw_message
from app.approvals.policy import ApprovalPolicy
from app.memory.cognee_store import MemoryItem
from app.tools.gws import GwsSheetsResult
from app.tools.openclaw import OpenClawResult


class FakeProvider:
    def __init__(self, responses: list[str] | None = None):
        self.system = ""
        self.user = ""
        self.calls: list[tuple[str, str]] = []
        self.responses = responses or ["done"]

    async def complete(self, system: str, user: str) -> str:
        self.system = system
        self.user = user
        self.calls.append((system, user))
        if len(self.calls) <= len(self.responses):
            return self.responses[len(self.calls) - 1]
        return self.responses[-1]


class FakeMemory:
    def __init__(self):
        self.last_query = ""
        self.remembered: list[tuple[str, str | None]] = []

    async def safe_recall(self, query: str):
        self.last_query = query
        return [MemoryItem(text=f"memory for {query}", source="test")], None

    async def remember(self, text: str, source: str | None = None):
        self.remembered.append((text, source))


class FakeQueue:
    pass


def test_preview_context_shows_recalled_memory_and_auto_skill(tmp_path):
    agent = AgentService(FakeProvider(["research"]), FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), FakeQueue())

    preview = asyncio.run(agent.preview_context("what did I work on emotions?", skill_name="auto"))

    assert preview.selected_skill == "research"
    assert preview.recall_error is None
    assert "[M1] (test) memory for what did I work on emotions?" in preview.context_packet
    assert preview.today_context == "No prior Telegram messages with the bot today."


def test_respond_sends_context_to_provider(tmp_path):
    provider = FakeProvider(["brainstorm", "done"])
    agent = AgentService(provider, FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), FakeQueue())

    response = asyncio.run(agent.respond("brainstorm ideas", skill_name="auto", today_context="Today with this Telegram chat: hi"))

    assert response == "done"
    assert "Skill: brainstorm" in provider.system
    assert "Today with this Telegram chat: hi" in provider.user
    assert "Focused long-term memory" in provider.user
    assert "User message:\nbrainstorm ideas" in provider.user
    assert "Memory scope:" in provider.system
    assert "Tool policy:" in provider.system
    assert "Output format:" in provider.system
    assert "Do not claim absolute lack of internet access" in provider.system


def test_llm_router_handles_typo_focus_request(tmp_path):
    provider = FakeProvider(["planner"])
    agent = AgentService(provider, FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), FakeQueue())

    preview = asyncio.run(agent.preview_context("what should I docus now", skill_name="auto"))

    assert preview.selected_skill == "planner"
    assert "Choose the best answer skill" in provider.calls[0][1]


def test_skill_limits_memory_context(tmp_path):
    class ManyMemory:
        async def safe_recall(self, query: str):
            return [MemoryItem(text=f"memory {index}", source="test") for index in range(6)], None

    agent = AgentService(FakeProvider(["debug"]), ManyMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), FakeQueue())

    preview = asyncio.run(agent.preview_context("debug this traceback", skill_name="auto"))

    assert preview.selected_skill == "debug"
    assert "[M1]" in preview.context_packet
    assert "[M2]" in preview.context_packet
    assert "[M3]" not in preview.context_packet


def test_openclaw_task_is_queued_by_default(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    from app.approvals import ApprovalQueue
    from app.storage import connect, init_db

    policy_path = tmp_path / "approvals.yaml"
    policy_path.write_text(
        "version: 1\ndefault: allow\ntools:\n  openclaw.agent_send:\n    mode: require_approval\n",
        encoding="utf-8",
    )
    init_db(db_path)
    with connect(db_path) as conn:
        queue = ApprovalQueue(conn)
        agent = AgentService(FakeProvider(), FakeMemory(), ApprovalPolicy(policy_path), queue)

        response = asyncio.run(agent.propose_openclaw_task("show recent photos", telegram_chat_id="123"))
        pending = queue.list_pending()

    assert "Queued OpenClaw task #1" in response
    assert pending[0].tool_name == "openclaw.agent_send"
    assert pending[0].payload["message"] == "show recent photos"
    assert pending[0].payload["session_id"] == "frakir-telegram-123"


def test_openclaw_web_search_tasks_get_search_instructions():
    message = prepare_openclaw_message("search the internet for ChatGPT macOS local storage")

    assert "Use web search/browser tools" in message
    assert "Answer in English" in message
    assert "Cite the sources" in message
    assert "User request:\nsearch the internet" in message


def test_openclaw_non_web_tasks_stay_plain():
    assert prepare_openclaw_message("inspect latest local logs") == "inspect latest local logs"


def test_memory_write_goes_to_palace_and_cognee(tmp_path):
    memory = FakeMemory()
    agent = AgentService(
        FakeProvider(),
        memory,
        ApprovalPolicy(tmp_path / "approvals.yaml"),
        FakeQueue(),
        memory_palace_dir=tmp_path / "Frakir Palace",
    )

    response = asyncio.run(agent.propose_memory_write("remember to my preferences: prefer concise answers"))
    palace_text = (tmp_path / "Frakir Palace" / "preferences.md").read_text(encoding="utf-8")

    assert "Stored in memory palace" in response
    assert "Indexed in Cognee source: palace:remember:preferences" in response
    assert "prefer concise answers" in palace_text
    assert memory.remembered[0][1] == "palace:remember:preferences"


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


def test_gws_sheets_create_is_queued_when_policy_requires_approval(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    from app.approvals import ApprovalQueue
    from app.storage import connect, init_db

    policy_path = tmp_path / "approvals.yaml"
    policy_path.write_text(
        "version: 1\ndefault: allow\ntools:\n  gws.sheets.create:\n    mode: require_approval\n",
        encoding="utf-8",
    )
    init_db(db_path)
    with connect(db_path) as conn:
        queue = ApprovalQueue(conn)
        agent = AgentService(FakeProvider(), FakeMemory(), ApprovalPolicy(policy_path), queue)

        response = asyncio.run(
            agent.propose_gws_sheets_action("gws.sheets.create", {"title": "Weekly Goals", "rows": [["Goal"]]})
        )
        pending = queue.list_pending()

    assert "Queued Google Workspace action #1" in response
    assert pending[0].tool_name == "gws.sheets.create"
    assert pending[0].payload == {"title": "Weekly Goals", "rows": [["Goal"]]}


def test_gws_approved_action_runs_tool(tmp_path, monkeypatch):
    from app.approvals import ApprovalQueue
    from app.approvals.queue import PendingAction
    from app.storage import connect, init_db
    import app.agent.service as service_module

    async def fake_create(title, rows):
        return GwsSheetsResult(operation="create", title=title, spreadsheet_id="sheet-123", updated_rows=len(rows))

    monkeypatch.setattr(service_module, "gws_create_spreadsheet", fake_create)
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)
    with connect(db_path) as conn:
        queue = ApprovalQueue(conn)
        agent = AgentService(FakeProvider(), FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), queue)

        response = asyncio.run(
            agent._execute_approved(
                PendingAction(
                    id=8,
                    tool_name="gws.sheets.create",
                    payload={"title": "Weekly Goals", "rows": [["Goal"]]},
                    status="pending",
                )
            )
        )

    assert "Google Sheets create complete." in response
    assert "Spreadsheet ID: sheet-123" in response
