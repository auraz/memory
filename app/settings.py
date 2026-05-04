from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    telegram_bot_token_frakir: str = ""
    llm_provider: str = Field(default="openai")
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-latest"
    obsidian_vault_path: Path = Path("../../1.Stable/ExpressionVault")
    chatgpt_export_path: Path | None = None
    claude_export_path: Path | None = None
    openclaw_export_path: Path | None = None
    sqlite_path: Path = Path("data/agent.sqlite")
    approval_policy_path: Path = Path("config/approvals.yaml")
    max_context_items: int = 8


settings = Settings()
