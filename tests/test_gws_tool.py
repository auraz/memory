from app.tools import gws


class FakeWorksheet:
    def __init__(self):
        self.updated = []
        self.appended = []
        self.values = [["Goal", "Status"], ["ship", "open"]]

    def update(self, *args, **kwargs):
        self.updated.append((args, kwargs))

    def append_rows(self, rows, value_input_option):
        self.appended.append((rows, value_input_option))

    def get(self, range_name):
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


def test_create_spreadsheet_seeds_rows(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(gws, "_build_client", lambda interactive: client)

    result = gws.create_spreadsheet(" Weekly   Goals ", [["Goal", "Status"], ["ship", "open"]])

    assert result.operation == "create"
    assert result.title == "Weekly Goals"
    assert result.spreadsheet_id == "sheet-123"
    assert result.updated_rows == 2
    assert client.created[0].sheet1.updated[0][1]["range_name"] == "A1"


def test_read_range_uses_named_sheet(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(gws, "_build_client", lambda interactive: client)

    result = gws.read_range("sheet-456", "Tasks!A1:B2")

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
