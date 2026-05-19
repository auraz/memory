import asyncio

from app.agent.service import AgentService, prepare_openclaw_message
from app.approvals import ApprovalQueue
from app.approvals.policy import ApprovalPolicy
from app.storage import connect, init_db


def test_openclaw_task_is_queued_by_policy(tmp_path):
    db_path = tmp_path / "agent.sqlite"
    policy_path = tmp_path / "approvals.yaml"
    policy_path.write_text(
        "version: 1\ndefault: allow\ntools:\n  openclaw.agent_send:\n    mode: require_approval\n",
        encoding="utf-8",
    )
    init_db(db_path)
    with connect(db_path) as conn:
        queue = ApprovalQueue(conn)
        agent = AgentService(None, None, ApprovalPolicy(policy_path), queue)  # type: ignore[arg-type]

        response = asyncio.run(agent.propose_openclaw_task("show recent photos", telegram_chat_id="123"))
        pending = queue.list_pending()

    assert "Queued OpenClaw task #1" in response
    assert pending[0].tool_name == "openclaw.agent_send"
    assert pending[0].payload["message"] == "show recent photos"
    assert pending[0].payload["session_id"] == "frakir-telegram-123"


def test_gws_sheets_create_runs_directly_even_when_policy_requires_approval(tmp_path, monkeypatch):
    import app.agent.service as service_module
    from app.tools.gws import GwsSheetsResult

    async def fake_create(title, rows):
        return GwsSheetsResult(operation="create", title=title, spreadsheet_id="sheet-123", updated_rows=len(rows))

    monkeypatch.setattr(service_module, "gws_create_spreadsheet", fake_create)
    db_path = tmp_path / "agent.sqlite"
    policy_path = tmp_path / "approvals.yaml"
    policy_path.write_text(
        "version: 1\ndefault: allow\ntools:\n  gws.sheets.create:\n    mode: require_approval\n",
        encoding="utf-8",
    )
    init_db(db_path)
    with connect(db_path) as conn:
        queue = ApprovalQueue(conn)
        agent = AgentService(None, None, ApprovalPolicy(policy_path), queue)  # type: ignore[arg-type]

        response = asyncio.run(
            agent.propose_gws_sheets_action("gws.sheets.create", {"title": "Weekly Goals", "rows": [["Goal"]]})
        )
        pending = queue.list_pending()

    assert "Google Sheets create complete." in response
    assert "Spreadsheet ID: sheet-123" in response
    assert pending == []


def test_gws_replace_approved_action_runs_tool(tmp_path, monkeypatch):
    import app.agent.service as service_module
    from app.approvals.queue import PendingAction
    from app.tools.gws import GwsSheetsResult

    async def fake_replace(spreadsheet_id, worksheet, rows):
        return GwsSheetsResult(
            operation="replace",
            spreadsheet_id=spreadsheet_id,
            range_name=worksheet or "Sheet1",
            updated_rows=len(rows),
        )

    monkeypatch.setattr(service_module, "gws_replace_worksheet", fake_replace)
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)
    with connect(db_path) as conn:
        queue = ApprovalQueue(conn)
        agent = AgentService(None, None, ApprovalPolicy(tmp_path / "approvals.yaml"), queue)  # type: ignore[arg-type]

        response = asyncio.run(
            agent._execute_approved(
                PendingAction(
                    id=8,
                    tool_name="gws.sheets.replace",
                    payload={"spreadsheet_id": "sheet-123", "worksheet": "", "rows": [["Name"], ["Grammarly"]]},
                    status="pending",
                )
            )
        )

    assert "Google Sheets replace complete." in response
    assert "Spreadsheet ID: sheet-123" in response
    assert "Rows: 2" in response


def test_gws_fill_column_approved_action_runs_tool(tmp_path, monkeypatch):
    import app.agent.service as service_module
    from app.approvals.queue import PendingAction
    from app.tools.gws import GwsSheetsResult

    async def fake_fill_column(spreadsheet_id, worksheet, header, value):
        return GwsSheetsResult(
            operation="fill_column",
            spreadsheet_id=spreadsheet_id,
            range_name=f"{worksheet or 'Sheet1'}!{header}",
            updated_rows=39,
        )

    monkeypatch.setattr(service_module, "gws_fill_column", fake_fill_column)
    db_path = tmp_path / "agent.sqlite"
    init_db(db_path)
    with connect(db_path) as conn:
        queue = ApprovalQueue(conn)
        agent = AgentService(None, None, ApprovalPolicy(tmp_path / "approvals.yaml"), queue)  # type: ignore[arg-type]

        response = asyncio.run(
            agent._execute_approved(
                PendingAction(
                    id=9,
                    tool_name="gws.sheets.fill_column",
                    payload={
                        "spreadsheet_id": "sheet-123",
                        "worksheet": "",
                        "header": "timezone",
                        "value": "Europe/Kyiv",
                    },
                    status="pending",
                )
            )
        )

    assert "Google Sheets fill_column complete." in response
    assert "Range: Sheet1!timezone" in response
    assert "Rows: 39" in response


def test_openclaw_web_search_tasks_get_search_instructions():
    message = prepare_openclaw_message("search the internet for ChatGPT macOS local storage")

    assert "Use web search/browser tools" in message
    assert "Answer in English" in message
    assert "Cite the sources" in message
    assert "User request:\nsearch the internet" in message


def test_openclaw_non_web_tasks_stay_plain():
    assert prepare_openclaw_message("inspect latest local logs") == "inspect latest local logs"
