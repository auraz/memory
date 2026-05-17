from app.bot.actions import (
    export_action_tool_schemas,
    is_allowed_during_memory_job,
    render_action_catalog,
    validate_action_args,
)


def test_action_catalog_renders_router_lines():
    catalog = render_action_catalog()

    assert "- chat: normal assistant conversation or task answer." in catalog
    assert "recall" in catalog
    assert "openclaw_delegate" in catalog
    assert "gws_sheets_create" in catalog
    assert '{"topic":"..."}' in catalog


def test_validate_action_args_normalizes_skill():
    args = validate_action_args("set_skill", {"skill": " Planner ", "ignored": True})

    assert args == {"skill": "planner"}


def test_validate_action_args_normalizes_goal_text():
    args = validate_action_args("goal", {"operation": "set", "text": "  success   business stories  "})

    assert args == {"operation": "set", "text": "success business stories"}


def test_validate_action_args_for_google_sheets_create():
    args = validate_action_args(
        "gws_sheets_create",
        {"title": " Weekly   Goals ", "rows": [["Goal", "Status"], ["Ship", "Open"]]},
    )

    assert args == {"title": "Weekly Goals", "rows": [["Goal", "Status"], ["Ship", "Open"]]}


def test_validate_action_args_rejects_unknown_action():
    assert validate_action_args("reset_memory", {"confirm": True}) == {}


def test_memory_job_allowlist_lives_in_action_specs():
    assert is_allowed_during_memory_job("memory_status") is True
    assert is_allowed_during_memory_job("refresh_memory") is False
    assert is_allowed_during_memory_job("chat") is False


def test_export_action_tool_schemas_as_mcp_tools():
    tools = export_action_tool_schemas("mcp")
    recall = next(tool for tool in tools if tool["name"] == "recall")
    goal = next(tool for tool in tools if tool["name"] == "goal")
    gws_create = next(tool for tool in tools if tool["name"] == "gws_sheets_create")

    assert recall["description"] == "Direct memory search/debug."
    assert recall["inputSchema"]["type"] == "object"
    assert "topic" in recall["inputSchema"]["properties"]
    assert "operation" in goal["inputSchema"]["properties"]
    assert "rows" in gws_create["inputSchema"]["properties"]


def test_export_action_tool_schemas_as_openai_tools():
    tools = export_action_tool_schemas("openai")
    recall = next(tool for tool in tools if tool["function"]["name"] == "recall")

    assert recall["type"] == "function"
    assert recall["function"]["parameters"]["type"] == "object"
    assert "topic" in recall["function"]["parameters"]["properties"]


def test_export_action_tool_schemas_rejects_unknown_format():
    try:
        export_action_tool_schemas("bad")  # type: ignore[arg-type]
    except ValueError as exc:
        assert "Unsupported tool schema format" in str(exc)
    else:
        raise AssertionError("expected ValueError")
