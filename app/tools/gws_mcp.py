from __future__ import annotations

import asyncio
import ast
import json
import re
import shlex
from typing import Any

from app.settings import settings
from app.tools.gws import GwsSheetsResult, SheetRows, SheetValue, extract_spreadsheet_id
from app.tools.mcp_client import McpToolResult, call_stdio_tool, list_stdio_tools


async def create_spreadsheet(title: str, rows: SheetRows | None = None) -> GwsSheetsResult:
    title = " ".join(title.split())
    if not title:
        raise ValueError("Spreadsheet title cannot be empty.")
    normalized_rows = _normalize_rows(rows or [])
    result = await _call_workspace_tool("create_spreadsheet", {"title": title})
    spreadsheet_id = _extract_spreadsheet_id(result)
    seeded_rows = 0
    details = result.text
    if normalized_rows:
        if not spreadsheet_id:
            raise RuntimeError("Workspace MCP created a spreadsheet but did not return a spreadsheet id for seeding rows.")
        update = await update_range(spreadsheet_id, "Sheet1!A1", normalized_rows)
        seeded_rows = update.updated_rows
        details = "\n".join(part for part in [details, update.details] if part)
    return GwsSheetsResult(
        operation="create",
        title=title,
        spreadsheet_id=spreadsheet_id,
        url=_extract_url(result),
        updated_rows=seeded_rows,
        details=details,
    )


async def read_range(spreadsheet_id: str, range_name: str) -> GwsSheetsResult:
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id)
    range_name = range_name.strip()
    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID cannot be empty.")
    if not range_name:
        raise ValueError("Range cannot be empty.")
    result = await _call_workspace_tool(
        "read_sheet_values",
        {"spreadsheet_id": spreadsheet_id, "range_name": range_name},
    )
    return GwsSheetsResult(
        operation="read",
        spreadsheet_id=spreadsheet_id,
        range_name=range_name,
        rows=_extract_rows(result),
        details=result.text,
    )


async def update_range(spreadsheet_id: str, range_name: str, values: SheetRows) -> GwsSheetsResult:
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id)
    range_name = range_name.strip()
    normalized_values = _normalize_rows(values)
    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID cannot be empty.")
    if not range_name:
        raise ValueError("Range cannot be empty.")
    if not normalized_values:
        raise ValueError("Values cannot be empty.")
    result = await _call_workspace_tool(
        "modify_sheet_values",
        {
            "spreadsheet_id": spreadsheet_id,
            "range_name": range_name,
            "values": normalized_values,
            "value_input_option": "USER_ENTERED",
        },
    )
    return GwsSheetsResult(
        operation="update",
        spreadsheet_id=spreadsheet_id,
        range_name=range_name,
        updated_rows=len(normalized_values),
        details=result.text,
    )


async def append_rows(spreadsheet_id: str, worksheet_name: str, rows: SheetRows) -> GwsSheetsResult:
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id)
    worksheet_name = (worksheet_name or "Sheet1").strip() or "Sheet1"
    normalized_rows = _normalize_rows(rows)
    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID cannot be empty.")
    if not normalized_rows:
        raise ValueError("Rows cannot be empty.")
    current = await read_range(spreadsheet_id, f"{worksheet_name}!A1:ZZ10000")
    existing_rows = current.rows
    if existing_rows is None:
        raise RuntimeError("Workspace MCP append requires structured rows from read_sheet_values.")
    start_row = len(existing_rows) + 1
    end_col = max(len(row) for row in normalized_rows)
    range_name = f"{worksheet_name}!{_a1(start_row, 1)}:{_a1(start_row + len(normalized_rows) - 1, end_col)}"
    result = await update_range(spreadsheet_id, range_name, normalized_rows)
    return GwsSheetsResult(
        operation="append",
        spreadsheet_id=spreadsheet_id,
        range_name=worksheet_name,
        updated_rows=result.updated_rows,
        details=result.details,
    )


async def replace_worksheet(spreadsheet_id: str, worksheet_name: str, rows: SheetRows) -> GwsSheetsResult:
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id)
    worksheet_name = (worksheet_name or "Sheet1").strip() or "Sheet1"
    normalized_rows = _normalize_rows(rows)
    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID cannot be empty.")
    if not normalized_rows:
        raise ValueError("Rows cannot be empty.")
    clear = await _call_workspace_tool(
        "modify_sheet_values",
        {
            "spreadsheet_id": spreadsheet_id,
            "range_name": f"{worksheet_name}!A1:ZZ10000",
            "clear_values": True,
        },
    )
    write = await update_range(spreadsheet_id, f"{worksheet_name}!A1", normalized_rows)
    details = "\n".join(part for part in [clear.text, write.details] if part)
    return GwsSheetsResult(
        operation="replace",
        spreadsheet_id=spreadsheet_id,
        range_name=worksheet_name,
        updated_rows=write.updated_rows,
        details=details,
    )


async def fill_column(spreadsheet_id: str, worksheet_name: str, header: str, value: SheetValue) -> GwsSheetsResult:
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id)
    worksheet_name = (worksheet_name or "Sheet1").strip() or "Sheet1"
    header = " ".join(str(header or "").split())
    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID cannot be empty.")
    if not header:
        raise ValueError("Column header cannot be empty.")
    current = await read_range(spreadsheet_id, f"{worksheet_name}!A1:ZZ10000")
    rows = current.rows
    if rows is None:
        raise RuntimeError("Workspace MCP fill_column requires structured rows from read_sheet_values.")
    headers = [str(cell).strip() for cell in rows[0]] if rows else []
    normalized_headers = [cell.lower() for cell in headers]
    if header.lower() in normalized_headers:
        column_index = normalized_headers.index(header.lower()) + 1
    else:
        column_index = len(headers) + 1
        await update_range(spreadsheet_id, f"{worksheet_name}!{_a1(1, column_index)}", [[header]])

    updated_rows = 0
    details = current.details
    if len(rows) > 1:
        values = [[_normalize_cell(value)] for _ in range(len(rows) - 1)]
        range_name = f"{worksheet_name}!{_a1(2, column_index)}:{_a1(len(rows), column_index)}"
        update = await update_range(spreadsheet_id, range_name, values)
        updated_rows = update.updated_rows
        details = update.details
    return GwsSheetsResult(
        operation="fill_column",
        spreadsheet_id=spreadsheet_id,
        range_name=f"{worksheet_name}!{header}",
        updated_rows=updated_rows,
        details=details,
    )


async def list_workspace_tools() -> list[dict[str, Any]]:
    return await list_stdio_tools(
        command=settings.gws_mcp_command,
        args=_mcp_args(),
        timeout_seconds=settings.gws_mcp_timeout_seconds,
    )


def list_tools_main() -> None:
    tools = asyncio.run(list_workspace_tools())
    print(json.dumps(tools, indent=2, sort_keys=True))


async def _call_workspace_tool(tool_name: str, tool_args: dict[str, Any]) -> McpToolResult:
    args = _with_user_google_email(tool_args)
    return await call_stdio_tool(
        command=settings.gws_mcp_command,
        args=_mcp_args(),
        tool_name=tool_name,
        tool_args=args,
        timeout_seconds=settings.gws_mcp_timeout_seconds,
    )


def _mcp_args() -> list[str]:
    return shlex.split(settings.gws_mcp_args)


def _with_user_google_email(tool_args: dict[str, Any]) -> dict[str, Any]:
    if "user_google_email" in tool_args:
        return tool_args
    email = settings.gws_mcp_user_google_email.strip()
    if not email:
        raise RuntimeError("GWS_MCP_USER_GOOGLE_EMAIL must be set when GWS_BACKEND=mcp.")
    return {"user_google_email": email, **tool_args}


def _extract_rows(result: McpToolResult) -> SheetRows | None:
    candidates = _walk_values(result.structured) + _json_text_candidates(result.text)
    for candidate in candidates:
        rows = _coerce_rows(candidate)
        if rows is not None:
            return rows
    parsed_rows = _rows_from_text(result.text)
    if parsed_rows is not None:
        return parsed_rows
    return None


def _rows_from_text(text: str) -> SheetRows | None:
    rows: SheetRows = []
    for line in text.splitlines():
        match = re.search(r"^\s*Row\s+\d+:\s+(\[.*\])\s*$", line)
        if not match:
            continue
        try:
            row = ast.literal_eval(match.group(1))
        except (SyntaxError, ValueError):
            return None
        if not isinstance(row, list):
            return None
        rows.append([_normalize_cell(cell) for cell in row])
    return rows or None


def _walk_values(value: Any) -> list[Any]:
    if value is None:
        return []
    candidates = [value]
    if isinstance(value, dict):
        for key in ("values", "rows", "data"):
            if key in value:
                candidates.extend(_walk_values(value[key]))
    return candidates


def _json_text_candidates(text: str) -> list[Any]:
    stripped = text.strip()
    if not stripped:
        return []
    try:
        return _walk_values(json.loads(stripped))
    except json.JSONDecodeError:
        return []


def _coerce_rows(value: Any) -> SheetRows | None:
    if not isinstance(value, list):
        return None
    if not value:
        return []
    if all(isinstance(row, list) for row in value):
        return [[_normalize_cell(cell) for cell in row] for row in value]
    return None


def _normalize_rows(rows: SheetRows) -> SheetRows:
    if not isinstance(rows, list) or any(not isinstance(row, list) for row in rows):
        raise ValueError("Rows must be a list of row lists.")
    return [[_normalize_cell(cell) for cell in row] for row in rows]


def _normalize_cell(value: SheetValue) -> SheetValue:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, str | int | float):
        return str(value)
    return str(value)


def _extract_spreadsheet_id(result: McpToolResult) -> str:
    for value in _walk_dicts(result.structured):
        for key in ("spreadsheet_id", "spreadsheetId", "id"):
            found = value.get(key)
            if isinstance(found, str) and found.strip():
                return extract_spreadsheet_id(found)
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", result.text)
    if match:
        return match.group(1)
    match = re.search(r"\bspreadsheet[_ ]?id[:=]\s*([a-zA-Z0-9_-]+)", result.text, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _extract_url(result: McpToolResult) -> str:
    for value in _walk_dicts(result.structured):
        for key in ("url", "spreadsheet_url", "spreadsheetUrl"):
            found = value.get(key)
            if isinstance(found, str) and found.startswith("http"):
                return found
    match = re.search(r"https://docs\.google\.com/spreadsheets/d/[a-zA-Z0-9_-]+[^\s)>\"]*", result.text)
    return match.group(0) if match else ""


def _walk_dicts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        found = [value]
        for child in value.values():
            found.extend(_walk_dicts(child))
        return found
    if isinstance(value, list):
        found: list[dict[str, Any]] = []
        for item in value:
            found.extend(_walk_dicts(item))
        return found
    return []


def _a1(row: int, col: int) -> str:
    letters = ""
    while col:
        col, remainder = divmod(col - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"
