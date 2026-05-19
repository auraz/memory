from app.agent.prompts import SYSTEM_PROMPT


def test_system_prompt_mentions_google_workspace_tool_path():
    assert "Frakir can use Google Workspace tools when configured" in SYSTEM_PROMPT
    assert "Workspace MCP backend" in SYSTEM_PROMPT
    assert "do not claim lack of Google access" in SYSTEM_PROMPT
