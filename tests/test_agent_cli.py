from app.agent_cli import parse_message_parts


def test_parse_message_parts_strips_separator():
    assert parse_message_parts(["--", "success", "business", "stories"]) == "success business stories"


def test_parse_message_parts_accepts_plain_remainder():
    assert parse_message_parts(["success", "business", "stories"]) == "success business stories"
