from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class ApprovalMode(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ToolRule(BaseModel):
    mode: ApprovalMode


class ApprovalPolicy:
    def __init__(self, path: Path):
        self.path = path
        self._raw = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "default": ApprovalMode.REQUIRE_APPROVAL.value, "tools": {}}
        with self.path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        loaded.setdefault("default", ApprovalMode.REQUIRE_APPROVAL.value)
        loaded.setdefault("tools", {})
        return loaded

    def reload(self) -> None:
        self._raw = self._load()

    def mode_for(self, tool_name: str) -> ApprovalMode:
        tool = self._raw.get("tools", {}).get(tool_name)
        if isinstance(tool, dict) and "mode" in tool:
            return ApprovalMode(tool["mode"])
        return ApprovalMode(self._raw.get("default", ApprovalMode.REQUIRE_APPROVAL.value))

    def is_allowed(self, tool_name: str) -> bool:
        return self.mode_for(tool_name) == ApprovalMode.ALLOW

    def requires_approval(self, tool_name: str) -> bool:
        return self.mode_for(tool_name) == ApprovalMode.REQUIRE_APPROVAL

    def is_denied(self, tool_name: str) -> bool:
        return self.mode_for(tool_name) == ApprovalMode.DENY

    def set_mode(self, tool_name: str, mode: ApprovalMode) -> None:
        self._raw.setdefault("tools", {})[tool_name] = {"mode": mode.value}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(self._raw, handle, sort_keys=True)

    def render(self) -> str:
        lines = [f"default: {self._raw.get('default')}"]
        for name, rule in sorted(self._raw.get("tools", {}).items()):
            mode = rule.get("mode", self._raw.get("default")) if isinstance(rule, dict) else rule
            lines.append(f"{name}: {mode}")
        return "\n".join(lines)

