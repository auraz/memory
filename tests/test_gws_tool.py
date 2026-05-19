import os

import pytest

from app.tools import gws


class FakeWorksheet:
    def __init__(self):
        self.updated = []
        self.appended = []
        self.cleared = False
        self.frozen = []
        self.resized = []
        self.title = "Sheet1"
        self.values = [["Goal", "Status"], ["ship", "open"]]
        self.cell_updates = []

    def update(self, *args, **kwargs):
        self.updated.append((args, kwargs))

    def update_cell(self, row, col, value):
        self.cell_updates.append((row, col, value))

    def clear(self):
        self.cleared = True

    def freeze(self, **kwargs):
        self.frozen.append(kwargs)

    def columns_auto_resize(self, start_column_index, end_column_index):
        self.resized.append((start_column_index, end_column_index))

    def append_rows(self, rows, value_input_option):
        self.appended.append((rows, value_input_option))

    def get(self, range_name):
        return self.values

    def row_values(self, row):
        return self.values[row - 1]

    def get_all_values(self):
        return self.values


class FakeSpreadsheet:
    def __init__(self, title="Weekly Goals"):
        self.title = title
        self.id = "sheet-123"
        self.url = "https://docs.google.com/spreadsheets/d/sheet-123"
        self.sheet1 = FakeWorksheet()
        self.named = {"Tasks": FakeWorksheet()}

    def worksheet(self, name):
        return self.named[name]


class FakeClient:
    def __init__(self):
        self.created = []
        self.opened = FakeSpreadsheet("Existing Sheet")

    def create(self, title):
        spreadsheet = FakeSpreadsheet(title)
        self.created.append(spreadsheet)
        return spreadsheet

    def open_by_key(self, spreadsheet_id):
        self.opened.id = spreadsheet_id
        return self.opened


def test_extract_spreadsheet_id_from_google_sheets_url():
    assert (
        gws.extract_spreadsheet_id("https://docs.google.com/spreadsheets/d/sheet-789/edit?gid=0#gid=0")
        == "sheet-789"
    )


def test_extract_spreadsheet_id_leaves_plain_id_unchanged():
    assert gws.extract_spreadsheet_id("sheet-123") == "sheet-123"


def test_create_spreadsheet_seeds_rows(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(gws, "_build_client", lambda interactive: client)

    result = gws.create_spreadsheet(" Weekly   Goals ", [["Goal", "Status"], ["ship", "open"]])

    assert result.operation == "create"
    assert result.title == "Weekly Goals"
    assert result.spreadsheet_id == "sheet-123"
    assert result.updated_rows == 2
    assert client.created[0].sheet1.updated[0][1]["range_name"] == "A1"


def test_read_range_extracts_id_from_url(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(gws, "_build_client", lambda interactive: client)

    result = gws.read_range("https://docs.google.com/spreadsheets/d/sheet-456/edit", "Tasks!A1:B2")

    assert result.operation == "read"
    assert result.spreadsheet_id == "sheet-456"
    assert result.rows == [["Goal", "Status"], ["ship", "open"]]


def test_update_range_and_append_rows(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(gws, "_build_client", lambda interactive: client)

    update = gws.update_range("sheet-456", "Tasks!A1:B1", [["Goal", "Status"]])
    append = gws.append_rows("sheet-456", "Tasks", [["ship", "open"]])

    assert update.updated_rows == 1
    assert append.updated_rows == 1
    assert client.opened.named["Tasks"].updated[0][1]["values"] == [["Goal", "Status"]]
    assert client.opened.named["Tasks"].appended[0] == ([["ship", "open"]], "USER_ENTERED")


def test_replace_worksheet_clears_and_writes_first_tab(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(gws, "_build_client", lambda interactive: client)

    result = gws.replace_worksheet("https://docs.google.com/spreadsheets/d/sheet-456/edit", "", [["Name"], ["Grammarly"]])

    assert result.operation == "replace"
    assert result.spreadsheet_id == "sheet-456"
    assert result.range_name == "Sheet1"
    assert result.updated_rows == 2
    assert client.opened.sheet1.cleared is True
    assert client.opened.sheet1.updated[0][1]["range_name"] == "A1"
    assert client.opened.sheet1.updated[0][1]["values"] == [["Name"], ["Grammarly"]]
    assert client.opened.sheet1.frozen == [{"rows": 1}]
    assert client.opened.sheet1.resized == [(0, 1)]


def test_fill_column_adds_header_and_fills_existing_rows(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(gws, "_build_client", lambda interactive: client)

    result = gws.fill_column("https://docs.google.com/spreadsheets/d/sheet-456/edit", "", "timezone", "Europe/Kyiv")

    assert result.operation == "fill_column"
    assert result.spreadsheet_id == "sheet-456"
    assert result.range_name == "Sheet1!timezone"
    assert result.updated_rows == 1
    assert client.opened.sheet1.cell_updates == [(1, 3, "timezone")]
    assert client.opened.sheet1.updated[0][1]["range_name"] == "C2:C2"
    assert client.opened.sheet1.updated[0][1]["values"] == [["Europe/Kyiv"]]


def test_split_range_handles_named_sheet_and_default_sheet():
    assert gws._split_range("Tasks!A1:B2") == ("Tasks", "A1:B2")
    assert gws._split_range("'Weekly Goals'!A1:B2") == ("Weekly Goals", "A1:B2")
    assert gws._split_range("A1:B2") == (None, "A1:B2")


def test_normalize_rows_rejects_non_row_values():
    with pytest.raises(ValueError, match="Rows must be a list of row lists"):
        gws._normalize_rows(["not a row"])


def test_normalize_rows_stringifies_complex_cells():
    assert gws._normalize_rows([["A", 1, 2.5, True, None, {"status": "open"}]]) == [
        ["A", 1, 2.5, True, None, "{'status': 'open'}"]
    ]


def test_result_render_includes_url_and_values():
    result = gws.GwsSheetsResult(
        operation="read",
        title="Sheet",
        spreadsheet_id="id",
        url="https://example.com",
        range_name="Sheet1!A1:B1",
        rows=[["A", "B"]],
    )

    rendered = result.render()

    assert "Google Sheets read complete." in rendered
    assert "https://example.com" in rendered
    assert "A\tB" in rendered


@pytest.mark.integration
def test_gws_read_range_real_sheet_when_configured():
    spreadsheet_id = os.environ.get("GWS_TEST_SPREADSHEET_ID")
    if not spreadsheet_id:
        pytest.skip("Set GWS_TEST_SPREADSHEET_ID to run real Google Sheets integration test.")

    result = gws.read_range(spreadsheet_id, os.environ.get("GWS_TEST_RANGE", "Sheet1!A1:A1"))

    assert result.operation == "read"
    assert result.spreadsheet_id == gws.extract_spreadsheet_id(spreadsheet_id)


@pytest.mark.integration
def test_gws_append_real_sheet_when_explicitly_enabled():
    spreadsheet_id = os.environ.get("GWS_TEST_SPREADSHEET_ID")
    if not spreadsheet_id or os.environ.get("GWS_TEST_WRITE") != "true":
        pytest.skip("Set GWS_TEST_SPREADSHEET_ID and GWS_TEST_WRITE=true to run write integration test.")

    result = gws.append_rows(spreadsheet_id, os.environ.get("GWS_TEST_WORKSHEET", "Sheet1"), [["Frakir test", "ok"]])

    assert result.operation == "append"
    assert result.updated_rows == 1
