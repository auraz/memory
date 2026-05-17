import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.bot.actions import ACTION_NAMES, render_action_catalog, validate_action_args
from app.providers.base import LLMProvider


@dataclass(frozen=True)
class NaturalIntent:
    intent: str
    confidence: float = 0.0
    args: dict[str, Any] = field(default_factory=dict)

    @property
    def should_handle(self) -> bool:
        return self.intent != "chat" and self.confidence >= 0.65


def build_intent_router_prompt(message: str) -> str:
    return (
        "Classify this Telegram message for Frakir, a local personal memory agent.\n"
        "Return strict JSON only: {\"intent\":\"...\",\"confidence\":0.0,\"args\":{...}}.\n"
        "Use `chat` unless the user is clearly asking to inspect/control Frakir itself.\n\n"
        "Allowed intents:\n"
        f"{render_action_catalog()}\n\n"
        "Do not choose recall/context_preview for ordinary questions like \"what should I focus on?\"; those are chat.\n"
        "Choose openclaw_delegate when the user asks to search, browse, look up current web info, inspect a website, or use internet access.\n"
        "Choose gws_sheets_* for Google Sheets creation, reading, updating, or row appends.\n"
        "Do not choose destructive/admin actions such as reset, rebuild, pkill, approval edits; leave those as chat or slash commands.\n\n"
        "Examples:\n"
        "show core memory -> show_core_memory\n"
        "memory status -> memory_status\n"
        "what memory jobs are running -> memory_jobs\n"
        "recall emotions -> recall {topic: emotions}\n"
        "context for what should I focus now -> context_preview {message: what should I focus now}\n"
        "use planner skill -> set_skill {skill: planner}\n"
        "skill auto -> set_skill {skill: auto}\n"
        "refresh memory -> refresh_memory\n"
        "remember that I prefer short answers -> remember {text: I prefer short answers}\n"
        "ask openclaw to inspect logs -> openclaw_delegate {task: inspect logs}\n"
        "search the internet for latest Letta docs -> openclaw_delegate {task: search the internet for latest Letta docs}\n"
        "look up current Apple developer renewal steps -> openclaw_delegate {task: look up current Apple developer renewal steps}\n"
        "create a Google Sheet called Weekly Goals with columns Goal, Owner, Status -> "
        "gws_sheets_create {title: Weekly Goals, rows: [[Goal, Owner, Status]]}\n"
        "read Sheet1 A1 to D20 from spreadsheet abc123 -> gws_sheets_read {spreadsheet_id: abc123, range: Sheet1!A1:D20}\n"
        "append rows to spreadsheet abc123 -> gws_sheets_append {spreadsheet_id: abc123, worksheet: Sheet1, rows: [[value]]}\n"
        "show goal -> goal {operation: show}\n"
        "set goal reuse OpenClaw for tools -> goal {operation: set, text: reuse OpenClaw for tools}\n"
        "goal status -> goal {operation: status}\n"
        "clear goal -> goal {operation: clear}\n"
        "what should I focus now -> chat\n\n"
        f"Message:\n{message}\n\n"
        "JSON:"
    )


async def route_natural_intent(provider: LLMProvider, message: str) -> NaturalIntent:
    try:
        raw = await provider.complete(
            "You classify user messages into Frakir intents. Return strict JSON only.",
            build_intent_router_prompt(message),
        )
        return parse_intent_router_output(raw)
    except Exception:
        return NaturalIntent(intent="chat", confidence=0.0)


def parse_intent_router_output(raw: str) -> NaturalIntent:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = json.loads(_extract_json_object(raw))
    if not isinstance(data, dict):
        return NaturalIntent(intent="chat", confidence=0.0)
    intent = str(data.get("intent", "chat")).strip().lower()
    if intent not in ACTION_NAMES:
        intent = "chat"
    confidence = _parse_confidence(data.get("confidence", 0.0))
    args = validate_action_args(intent, data.get("args", {}))
    return NaturalIntent(intent=intent, confidence=confidence, args=args)


def _parse_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(max(parsed, 0.0), 1.0)


def _extract_json_object(raw: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise json.JSONDecodeError("No JSON object found", raw, 0)
    return raw[start : end + 1]
