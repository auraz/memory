import asyncio

import pytest

from app.tools import openclaw


def test_extract_text_from_json_output():
    assert openclaw._extract_text('{"reply": "done"}') == "done"
    assert openclaw._extract_text('{"result": {"content": "nested"}}') == "nested"


def test_extract_text_falls_back_to_plain_output():
    assert openclaw._extract_text("plain text") == "plain text"


def test_run_openclaw_agent_reports_missing_cli():
    with pytest.raises(RuntimeError, match="OpenClaw CLI not found"):
        asyncio.run(
            openclaw.run_openclaw_agent(
                message="hello",
                session_id="test",
                cli_path="/definitely/missing/openclaw",
                timeout_seconds=1,
            )
        )
