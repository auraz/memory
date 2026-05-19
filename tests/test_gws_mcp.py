import asyncio

from app.tools import gws_mcp
from app.tools.mcp_client import McpToolResult


def test_mcp_read_range_uses_workspace_tool(monkeypatch):
    calls = []

    async def fake_call(tool_name, tool_args):
        calls.append((tool_name, tool_args))
        return McpToolResult(
            tool_name=tool_name,
            text="",
            structured={"values": [["Name", "Status"], ["Frakir", "Active"]]},
        )

    monkeypatch.setattr(gws_mcp, "_call_workspace_tool", fake_call)

    result = asyncio.run(
        gws_mcp.read_range("https://docs.google.com/spreadsheets/d/sheet-123/edit", "Sheet1!A1:B2")
    )

    assert result.operation == "read"
    assert result.spreadsheet_id == "sheet-123"
    assert result.rows == [["Name", "Status"], ["Frakir", "Active"]]
    assert calls == [
        (
            "read_sheet_values",
            {"spreadsheet_id": "sheet-123", "range_name": "Sheet1!A1:B2"},
        )
    ]


def test_mcp_update_range_uses_modify_sheet_values(monkeypatch):
    calls = []

    async def fake_call(tool_name, tool_args):
        calls.append((tool_name, tool_args))
        return McpToolResult(tool_name=tool_name, text="updated")

    monkeypatch.setattr(gws_mcp, "_call_workspace_tool", fake_call)

    result = asyncio.run(gws_mcp.update_range("sheet-123", "Sheet1!A1:D1", [["Name", 42, True, None]]))

    assert result.operation == "update"
    assert result.updated_rows == 1
    assert calls == [
        (
            "modify_sheet_values",
            {
                "spreadsheet_id": "sheet-123",
                "range_name": "Sheet1!A1:D1",
                "values": [["Name", "42", "TRUE", ""]],
                "value_input_option": "USER_ENTERED",
            },
        )
    ]


def test_mcp_fill_column_composes_read_and_updates(monkeypatch):
    calls = []

    async def fake_call(tool_name, tool_args):
        calls.append((tool_name, tool_args))
        if tool_name == "read_sheet_values":
            return McpToolResult(
                tool_name=tool_name,
                text="",
                structured={"values": [["company", "country"], ["Grammarly", "Ukraine"], ["Ajax", "Ukraine"]]},
            )
        return McpToolResult(tool_name=tool_name, text="updated")

    monkeypatch.setattr(gws_mcp, "_call_workspace_tool", fake_call)

    result = asyncio.run(gws_mcp.fill_column("sheet-123", "Sheet1", "timezone", "Europe/Kyiv"))

    assert result.operation == "fill_column"
    assert result.range_name == "Sheet1!timezone"
    assert result.updated_rows == 2
    assert calls == [
        ("read_sheet_values", {"spreadsheet_id": "sheet-123", "range_name": "Sheet1!A1:ZZ10000"}),
        (
            "modify_sheet_values",
            {
                "spreadsheet_id": "sheet-123",
                "range_name": "Sheet1!C1",
                "values": [["timezone"]],
                "value_input_option": "USER_ENTERED",
            },
        ),
        (
            "modify_sheet_values",
            {
                "spreadsheet_id": "sheet-123",
                "range_name": "Sheet1!C2:C3",
                "values": [["Europe/Kyiv"], ["Europe/Kyiv"]],
                "value_input_option": "USER_ENTERED",
            },
        ),
    ]


def test_mcp_tool_args_include_configured_user_google_email(monkeypatch):
    monkeypatch.setattr(gws_mcp.settings, "gws_mcp_user_google_email", "ok@example.com")

    assert gws_mcp._with_user_google_email({"spreadsheet_id": "sheet-123"}) == {
        "user_google_email": "ok@example.com",
        "spreadsheet_id": "sheet-123",
    }


def test_extract_rows_from_workspace_mcp_text_result():
    result = gws_mcp._extract_rows(
        gws_mcp.McpToolResult(
            tool_name="read_sheet_values",
            text=(
                "Successfully read 2 rows:\n"
                "Row  1: ['Name', 'timezone']\n"
                "Row  2: ['Grammarly', 'Europe/Kyiv']\n"
            ),
        )
    )

    assert result == [["Name", "timezone"], ["Grammarly", "Europe/Kyiv"]]
