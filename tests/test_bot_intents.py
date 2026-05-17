import asyncio

from app.bot.intents import parse_intent_router_output, route_natural_intent


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


def test_route_natural_intent_uses_llm_provider():
    provider = FakeProvider('{"intent":"set_skill","confidence":0.88,"args":{"skill":"planner"}}')

    intent = asyncio.run(route_natural_intent(provider, "use planner skill"))

    assert intent.intent == "set_skill"
    assert intent.args == {"skill": "planner"}
    assert "Classify this Telegram message" in provider.calls[0][1]
    assert "look up current web info" in provider.calls[0][1]


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


def test_intent_prompt_routes_web_requests_to_openclaw():
    from app.bot.intents import build_intent_router_prompt

    prompt = build_intent_router_prompt("search the internet for latest Letta docs")

    assert "search the internet for latest Letta docs -> openclaw_delegate" in prompt
    assert "use internet access" in prompt


def test_intent_prompt_routes_google_sheets_requests_to_gws():
    from app.bot.intents import build_intent_router_prompt

    prompt = build_intent_router_prompt("create a Google Sheet called Weekly Goals")

    assert "Choose gws_sheets_*" in prompt
    assert "create a Google Sheet called Weekly Goals" in prompt
