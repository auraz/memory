from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    telegram_bot_token_frakir: str = ""
    llm_provider: str = Field(default="openai")
    openai_api_key: str = ""
    openai_model: str = "gpt-5.5"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-latest"
    obsidian_vault_path: Path = Path("../../1.Stable/ExpressionVault")
    chatgpt_export_path: Path | None = None
    claude_export_path: Path | None = None
    openclaw_export_path: Path | None = None
    openclaw_workspace_path: Path = Path("~/.openclaw/workspace")
    claude_projects_path: Path = Path("~/.claude/projects")
    codex_projects_path: Path = Path("~/.codex/projects")
    claude_project_memory_path: Path = Path("~/.claude/projects/-Users-ok--openclaw-workspace/memory")
    openclaw_sessions_path: Path = Path("~/.openclaw/sessions")
    claude_global_path: Path = Path("~/.claude/CLAUDE.md")
    sqlite_path: Path = Path("data/agent.sqlite")
    approval_policy_path: Path = Path("config/approvals.yaml")
    max_context_items: int = 8
    focused_context_items: int = 4
    focused_context_chars: int = 2200
    focused_memory_item_chars: int = 500
    core_memory_chars: int = 3500
    core_memory_auto_update: bool = True
    letta_enabled: bool = False
    letta_api_key: str = ""
    letta_base_url: str = ""
    letta_agent_id: str = ""
    openclaw_cli_path: str = "openclaw"
    openclaw_agent_id: str | None = None
    openclaw_local: bool = True
    openclaw_timeout_seconds: int = 600
    gws_client_secret_path: Path = Path("config/google/client_secret.json")
    gws_authorized_user_path: Path = Path("data/google/authorized_user.json")
    gws_scopes: str = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/spreadsheets"
    gws_backend: str = "local"
    gws_mcp_command: str = "uvx"
    gws_mcp_args: str = "workspace-mcp --tool-tier core"
    gws_mcp_user_google_email: str = ""
    gws_mcp_timeout_seconds: int = 120
    apfel_cli_path: str = "apfel"
    apfel_summary_sources: str = "claude_projects"
    apfel_summary_min_chars: int = 8000
    apfel_summary_chunk_chars: int = 1800
    apfel_summary_max_chunks: int = 12
    apfel_summary_timeout_seconds: int = 180
    apfel_rolling_summary_max_chars: int = 1800
    apfel_translate_unsupported_language: bool = True
    apfel_llm_fallback_on_unsupported_language: bool = True


settings = Settings()
