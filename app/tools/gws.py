from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
import re
from typing import Any

from app.settings import settings

SheetValue = str | int | float | bool | None
SheetRows = list[list[SheetValue]]


@dataclass(frozen=True)
class GwsSheetsResult:
    operation: str
    title: str = ""
    spreadsheet_id: str = ""
    url: str = ""
    range_name: str = ""
    rows: SheetRows | None = None
    updated_rows: int = 0
    details: str = ""

    def render(self) -> str:
        lines = [f"Google Sheets {self.operation} complete."]
        if self.title:
            lines.append(f"Title: {self.title}")
        if self.spreadsheet_id:
            lines.append(f"Spreadsheet ID: {self.spreadsheet_id}")
        if self.url:
            lines.append(f"URL: {self.url}")
        if self.range_name:
            lines.append(f"Range: {self.range_name}")
        if self.updated_rows:
            lines.append(f"Rows: {self.updated_rows}")
        if self.rows is not None:
            preview = _preview_rows(self.rows)
            lines.append(f"Values:\n{preview}" if preview else "Values: empty")
        if self.details:
            lines.append(f"Details:\n{self.details}")
        return "\n".join(lines)


def authorize_google_workspace(interactive: bool = True) -> GwsSheetsResult:
    client = _build_client(interactive=interactive)
    user = getattr(client, "auth", None)
    return GwsSheetsResult(operation="auth", title=type(user).__name__ if user else "authorized")


def create_spreadsheet(title: str, rows: SheetRows | None = None) -> GwsSheetsResult:
    title = " ".join(title.split())
    if not title:
        raise ValueError("Spreadsheet title cannot be empty.")
    client = _build_client(interactive=False)
    spreadsheet = client.create(title)
    normalized_rows = _normalize_rows(rows or [])
    if normalized_rows:
        _worksheet_update(spreadsheet.sheet1, "A1", normalized_rows)
    return GwsSheetsResult(
        operation="create",
        title=_attr(spreadsheet, "title", title),
        spreadsheet_id=_attr(spreadsheet, "id", ""),
        url=_attr(spreadsheet, "url", ""),
        updated_rows=len(normalized_rows),
    )


def read_range(spreadsheet_id: str, range_name: str) -> GwsSheetsResult:
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id)
    range_name = range_name.strip()
    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID cannot be empty.")
    if not range_name:
        raise ValueError("Range cannot be empty.")
    client = _build_client(interactive=False)
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet_name, cell_range = _split_range(range_name)
    worksheet = _worksheet(spreadsheet, worksheet_name)
    values = worksheet.get(cell_range)
    return GwsSheetsResult(
        operation="read",
        title=_attr(spreadsheet, "title", ""),
        spreadsheet_id=spreadsheet_id,
        url=_attr(spreadsheet, "url", ""),
        range_name=range_name,
        rows=_normalize_rows(values),
    )


def update_range(spreadsheet_id: str, range_name: str, values: SheetRows) -> GwsSheetsResult:
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id)
    range_name = range_name.strip()
    normalized_values = _normalize_rows(values)
    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID cannot be empty.")
    if not range_name:
        raise ValueError("Range cannot be empty.")
    if not normalized_values:
        raise ValueError("Values cannot be empty.")
    client = _build_client(interactive=False)
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet_name, cell_range = _split_range(range_name)
    worksheet = _worksheet(spreadsheet, worksheet_name)
    _worksheet_update(worksheet, cell_range, normalized_values)
    return GwsSheetsResult(
        operation="update",
        title=_attr(spreadsheet, "title", ""),
        spreadsheet_id=spreadsheet_id,
        url=_attr(spreadsheet, "url", ""),
        range_name=range_name,
        updated_rows=len(normalized_values),
    )


def append_rows(spreadsheet_id: str, worksheet_name: str, rows: SheetRows) -> GwsSheetsResult:
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id)
    worksheet_name = (worksheet_name or "Sheet1").strip() or "Sheet1"
    normalized_rows = _normalize_rows(rows)
    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID cannot be empty.")
    if not normalized_rows:
        raise ValueError("Rows cannot be empty.")
    client = _build_client(interactive=False)
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = _worksheet(spreadsheet, worksheet_name)
    worksheet.append_rows(normalized_rows, value_input_option="USER_ENTERED")
    return GwsSheetsResult(
        operation="append",
        title=_attr(spreadsheet, "title", ""),
        spreadsheet_id=spreadsheet_id,
        url=_attr(spreadsheet, "url", ""),
        range_name=worksheet_name,
        updated_rows=len(normalized_rows),
    )


def replace_worksheet(spreadsheet_id: str, worksheet_name: str, rows: SheetRows) -> GwsSheetsResult:
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id)
    worksheet_name = (worksheet_name or "").strip()
    normalized_rows = _normalize_rows(rows)
    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID cannot be empty.")
    if not normalized_rows:
        raise ValueError("Rows cannot be empty.")
    client = _build_client(interactive=False)
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = _worksheet(spreadsheet, worksheet_name or None)
    worksheet.clear()
    _worksheet_update(worksheet, "A1", normalized_rows)
    with suppress(Exception):
        worksheet.freeze(rows=1)
    with suppress(Exception):
        worksheet.columns_auto_resize(0, len(normalized_rows[0]))
    return GwsSheetsResult(
        operation="replace",
        title=_attr(spreadsheet, "title", ""),
        spreadsheet_id=spreadsheet_id,
        url=_attr(spreadsheet, "url", ""),
        range_name=worksheet_name or _attr(worksheet, "title", "first worksheet"),
        updated_rows=len(normalized_rows),
    )


def fill_column(spreadsheet_id: str, worksheet_name: str, header: str, value: SheetValue) -> GwsSheetsResult:
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_id)
    worksheet_name = (worksheet_name or "").strip()
    header = " ".join(str(header or "").split())
    if not spreadsheet_id:
        raise ValueError("Spreadsheet ID cannot be empty.")
    if not header:
        raise ValueError("Column header cannot be empty.")
    client = _build_client(interactive=False)
    spreadsheet = client.open_by_key(spreadsheet_id)
    worksheet = _worksheet(spreadsheet, worksheet_name or None)
    headers = [str(cell).strip() for cell in worksheet.row_values(1)]
    normalized_headers = [cell.lower() for cell in headers]
    if header.lower() in normalized_headers:
        column_index = normalized_headers.index(header.lower()) + 1
    else:
        column_index = len(headers) + 1
        worksheet.update_cell(1, column_index, header)

    row_count = len(worksheet.get_all_values())
    updated_rows = 0
    if row_count > 1:
        values = [[_normalize_cell(value)] for _ in range(row_count - 1)]
        range_name = f"{_a1(2, column_index)}:{_a1(row_count, column_index)}"
        _worksheet_update(worksheet, range_name, values)
        updated_rows = len(values)
    return GwsSheetsResult(
        operation="fill_column",
        title=_attr(spreadsheet, "title", ""),
        spreadsheet_id=spreadsheet_id,
        url=_attr(spreadsheet, "url", ""),
        range_name=f"{worksheet_name or _attr(worksheet, 'title', 'first worksheet')}!{header}",
        updated_rows=updated_rows,
    )


def main() -> None:
    result = authorize_google_workspace(interactive=True)
    print(result.render())


def _build_client(interactive: bool):
    gspread = _gspread()
    client_secret = _expand(settings.gws_client_secret_path)
    authorized_user = _expand(settings.gws_authorized_user_path)
    if not client_secret.exists():
        raise RuntimeError(
            f"Google OAuth client secret not found: {client_secret}. "
            "Create an OAuth desktop client in Google Cloud and save it there."
        )
    if not interactive and not authorized_user.exists():
        raise RuntimeError(f"Google authorized user token not found: {authorized_user}. Run `gws-auth` first.")
    authorized_user.parent.mkdir(parents=True, exist_ok=True)
    return gspread.oauth(
        credentials_filename=str(client_secret),
        authorized_user_filename=str(authorized_user),
        scopes=_scopes(),
    )


def extract_spreadsheet_id(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", text)
    if match:
        return match.group(1)
    return text


def _gspread():
    try:
        return import_module("gspread")
    except ModuleNotFoundError as exc:
        raise RuntimeError("Google Workspace support is not installed. Run `uv sync` or reinstall the package.") from exc


def _scopes() -> list[str]:
    return [scope for scope in settings.gws_scopes.split() if scope]


def _expand(path: Path) -> Path:
    return path.expanduser()


def _worksheet(spreadsheet: Any, worksheet_name: str | None):
    if worksheet_name:
        return spreadsheet.worksheet(worksheet_name)
    return spreadsheet.sheet1


def _split_range(range_name: str) -> tuple[str | None, str]:
    if "!" not in range_name:
        return None, range_name
    worksheet_name, cell_range = range_name.split("!", 1)
    worksheet_name = worksheet_name.strip().strip("'")
    cell_range = cell_range.strip()
    return worksheet_name or None, cell_range


def _worksheet_update(worksheet: Any, range_name: str, values: SheetRows) -> None:
    try:
        worksheet.update(values=values, range_name=range_name, value_input_option="USER_ENTERED")
    except TypeError:
        worksheet.update(range_name, values, value_input_option="USER_ENTERED")


def _normalize_rows(rows: Any) -> SheetRows:
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError("Rows must be a list of row lists.")
    normalized: SheetRows = []
    for row in rows:
        if not isinstance(row, list):
            raise ValueError("Rows must be a list of row lists.")
        normalized.append([_normalize_cell(cell) for cell in row])
    return normalized


def _normalize_cell(value: Any) -> SheetValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _preview_rows(rows: SheetRows, max_rows: int = 8, max_chars: int = 1200) -> str:
    rendered = "\n".join("\t".join("" if cell is None else str(cell) for cell in row) for row in rows[:max_rows])
    if len(rows) > max_rows:
        rendered += f"\n... {len(rows) - max_rows} more row(s)"
    if len(rendered) > max_chars:
        rendered = rendered[: max_chars - 3].rstrip() + "..."
    return rendered


def _a1(row: int, column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"


def _attr(value: Any, name: str, default: str) -> str:
    result = getattr(value, name, default)
    return str(result or default)
