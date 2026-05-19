import asyncio

from app.bot.intents import build_intent_router_prompt, deterministic_intent, parse_intent_router_output, route_natural_intent


class FakeProvider:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


def test_parse_intent_router_output_accepts_fenced_json():
    intent = parse_intent_router_output(
        '```json\n{"intent":"recall","confidence":0.91,"args":{"topic":"emotions"}}\n```'
    )

    assert intent.intent == "recall"
    assert intent.confidence == 0.91
    assert intent.args == {"topic": "emotions"}
    assert intent.should_handle is True


def test_parse_intent_router_output_clamps_confidence():
    intent = parse_intent_router_output('{"intent":"memory_status","confidence":9,"args":{}}')

    assert intent.intent == "memory_status"
    assert intent.confidence == 1.0


def test_parse_intent_router_output_rejects_unknown_intent():
    intent = parse_intent_router_output('{"intent":"reset_memory","confidence":1,"args":{}}')

    assert intent.intent == "chat"
    assert intent.should_handle is False


def test_parse_intent_router_output_requires_confidence_threshold():
    intent = parse_intent_router_output('{"intent":"refresh_memory","confidence":0.4,"args":{}}')

    assert intent.intent == "refresh_memory"
    assert intent.should_handle is False


def test_deterministic_google_sheets_guard_appends_rows():
    message = (
        "append row to https://docs.google.com/spreadsheets/d/1rA5JOtoa6ai3j_ZIv0GFsKxzE7_ryw-P2KoFx-vyirY/edit "
        "Item: Frakir GWS test Status: working"
    )

    intent = deterministic_intent(message)

    assert intent is not None
    assert intent.intent == "gws_sheets_append"
    assert intent.confidence == 1.0
    assert intent.args["spreadsheet_id"].endswith("/1rA5JOtoa6ai3j_ZIv0GFsKxzE7_ryw-P2KoFx-vyirY/edit")
    assert intent.args["worksheet"] == "Sheet1"
    assert "Frakir GWS test" in intent.args["rows"][0][0]


def test_deterministic_google_sheets_guard_extracts_named_row_text():
    intent = deterministic_intent("add test row to https://docs.google.com/spreadsheets/d/sheet-123/edit")

    assert intent is not None
    assert intent.intent == "gws_sheets_append"
    assert intent.args["rows"] == [["test"]]


def test_deterministic_google_sheets_guard_reads_by_default_range():
    intent = deterministic_intent("read https://docs.google.com/spreadsheets/d/sheet-123/edit")

    assert intent is not None
    assert intent.intent == "gws_sheets_read"
    assert intent.args == {
        "spreadsheet_id": "https://docs.google.com/spreadsheets/d/sheet-123/edit",
        "range": "Sheet1!A1:Z100",
    }


def test_deterministic_google_sheets_guard_fills_timezone_column():
    intent = deterministic_intent(
        "add timezone column Europe/Kyiv to https://docs.google.com/spreadsheets/d/sheet-123/edit"
    )

    assert intent is not None
    assert intent.intent == "gws_sheets_fill_column"
    assert intent.args == {
        "spreadsheet_id": "https://docs.google.com/spreadsheets/d/sheet-123/edit",
        "worksheet": "",
        "header": "timezone",
        "value": "Europe/Kyiv",
    }


def test_deterministic_google_sheets_guard_ignores_plain_chat():
    assert deterministic_intent("what is the best way to use spreadsheets?") is None


def test_route_natural_intent_uses_llm_provider_when_no_deterministic_match():
    provider = FakeProvider('{"intent":"set_skill","confidence":0.88,"args":{"skill":"planner"}}')

    intent = asyncio.run(route_natural_intent(provider, "use planner skill", recent_context="Today: prior target"))

    assert intent.intent == "set_skill"
    assert intent.args == {"skill": "planner"}
    assert "Classify this Telegram message" in provider.calls[0][1]
    assert "look up current web info" in provider.calls[0][1]
    assert "Recent Telegram context:" in provider.calls[0][1]
    assert "Today: prior target" in provider.calls[0][1]


def test_parse_goal_intent():
    intent = parse_intent_router_output(
        '{"intent":"goal","confidence":0.9,"args":{"operation":"set","text":" success  business stories "}}'
    )

    assert intent.intent == "goal"
    assert intent.args == {"operation": "set", "text": "success business stories"}


def test_parse_google_sheets_create_intent():
    intent = parse_intent_router_output(
        '{"intent":"gws_sheets_create","confidence":0.9,'
        '"args":{"title":" Weekly   Goals ","rows":[["Goal","Status"]]}}'
    )

    assert intent.intent == "gws_sheets_create"
    assert intent.args == {"title": "Weekly Goals", "rows": [["Goal", "Status"]]}


def test_parse_google_sheets_replace_intent():
    intent = parse_intent_router_output(
        '{"intent":"gws_sheets_replace","confidence":0.92,'
        '"args":{"spreadsheet_id":"sheet-123","worksheet":"","rows":[["Name"],["Grammarly"]]}}'
    )

    assert intent.intent == "gws_sheets_replace"
    assert intent.args == {"spreadsheet_id": "sheet-123", "worksheet": "", "rows": [["Name"], ["Grammarly"]]}


def test_parse_google_sheets_fill_column_intent():
    intent = parse_intent_router_output(
        '{"intent":"gws_sheets_fill_column","confidence":0.92,'
        '"args":{"spreadsheet_id":"sheet-123","worksheet":"","header":" timezone ","value":"Europe/Kyiv"}}'
    )

    assert intent.intent == "gws_sheets_fill_column"
    assert intent.args == {"spreadsheet_id": "sheet-123", "worksheet": "", "header": "timezone", "value": "Europe/Kyiv"}


def test_intent_prompt_routes_google_sheets_urls_to_gws():
    prompt = build_intent_router_prompt("add test row to https://docs.google.com/spreadsheets/d/abc123/edit")

    assert "A Google Sheets URL is enough" in prompt
    assert "gws_sheets_append" in prompt
    assert "gws_sheets_fill_column" in prompt


def test_intent_prompt_resolves_target_operation_from_recent_context():
    prompt = build_intent_router_prompt(
        "can you execute target operation?",
        recent_context="Target operation: clear first tab of spreadsheet abc123 and write rows [[Name], [Grammarly]].",
    )

    assert "Recent Telegram context:" in prompt
    assert "execute target operation" in prompt
    assert "gws_sheets_replace" in prompt
