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


GOOGLE_SHEETS_URL_RE = re.compile(r"https?://docs\.google\.com/spreadsheets/d/[a-zA-Z0-9_-]+[^\s]*", re.IGNORECASE)
SHEETS_READ_WORDS = ("read", "show", "check", "get", "fetch", "look")
SHEETS_APPEND_WORDS = ("append", "add row", "add rows", "insert row", "insert rows", "add this", "log")
SHEETS_UPDATE_WORDS = ("update", "edit", "change", "set", "write", "put", "fill")
TIMEZONE_RE = re.compile(r"\b(timezone|time zone)\b.*\b([A-Za-z]+/[A-Za-z_]+)\b", re.IGNORECASE)


def deterministic_intent(message: str) -> NaturalIntent | None:
    match = GOOGLE_SHEETS_URL_RE.search(message)
    if not match:
        return None
    remainder = GOOGLE_SHEETS_URL_RE.sub("", message)
    lower = remainder.lower()
    spreadsheet_id = match.group(0)
    if "column" in lower and (timezone := TIMEZONE_RE.search(remainder)):
        return NaturalIntent(
            intent="gws_sheets_fill_column",
            confidence=1.0,
            args={"spreadsheet_id": spreadsheet_id, "worksheet": "", "header": "timezone", "value": timezone.group(2)},
        )
    if any(word in lower for word in SHEETS_APPEND_WORDS) or re.search(r"\badd\b.+\brows?\b", lower):
        return NaturalIntent(
            intent="gws_sheets_append",
            confidence=1.0,
            args={"spreadsheet_id": spreadsheet_id, "worksheet": "Sheet1", "rows": [[_compact_sheet_row_text(message)]]},
        )
    if any(word in lower for word in SHEETS_UPDATE_WORDS):
        return NaturalIntent(
            intent="gws_sheets_update",
            confidence=1.0,
            args={"spreadsheet_id": spreadsheet_id, "range": "Sheet1!A1", "values": [[_compact_sheet_row_text(message)]]},
        )
    if any(word in lower for word in SHEETS_READ_WORDS):
        return NaturalIntent(
            intent="gws_sheets_read",
            confidence=1.0,
            args={"spreadsheet_id": spreadsheet_id, "range": "Sheet1!A1:Z100"},
        )
    return None


def build_intent_router_prompt(message: str, recent_context: str | None = None) -> str:
    context_section = f"Recent Telegram context:\n{recent_context}\n\n" if recent_context else ""
    return (
        "Classify this Telegram message for Frakir, a local personal memory agent.\n"
        "Return strict JSON only: {\"intent\":\"...\",\"confidence\":0.0,\"args\":{...}}.\n"
        "Use `chat` unless the user is clearly asking to inspect/control Frakir itself.\n\n"
        "Allowed intents:\n"
        f"{render_action_catalog()}\n\n"
        "Do not choose recall/context_preview for ordinary questions like \"what should I focus on?\"; those are chat.\n"
        "Choose openclaw_delegate when the user asks to search, browse, look up current web info, inspect a website, or use internet access.\n"
        "Choose gws_sheets_* for Google Sheets creation, reading, updating, row appends, column fills, or full table replacement. "
        "A Google Sheets URL is enough; place the full URL in spreadsheet_id.\n"
        "Use recent Telegram context to resolve short follow-ups like `do it`, `go`, or `execute target operation`. "
        "Only choose a Google Sheets action from context when the target spreadsheet and required values are explicit. "
        "For clear-and-write table requests, choose gws_sheets_replace. "
        "For add/reuse a column and fill existing rows with one value, choose gws_sheets_fill_column.\n"
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
        "add test row to https://docs.google.com/spreadsheets/d/abc123/edit -> "
        "gws_sheets_append {spreadsheet_id: https://docs.google.com/spreadsheets/d/abc123/edit, worksheet: Sheet1, rows: [[test]]}\n"
        "add timezone column with Europe/Kyiv to spreadsheet abc123 -> "
        "gws_sheets_fill_column {spreadsheet_id: abc123, worksheet: \"\", header: timezone, value: Europe/Kyiv}\n"
        "execute target operation, with recent context containing sheet abc123 and rows -> "
        "gws_sheets_replace {spreadsheet_id: abc123, worksheet: \"\", rows: [[header], [value]]}\n"
        "show goal -> goal {operation: show}\n"
        "set goal reuse OpenClaw for tools -> goal {operation: set, text: reuse OpenClaw for tools}\n"
        "goal status -> goal {operation: status}\n"
        "clear goal -> goal {operation: clear}\n"
        "what should I focus now -> chat\n\n"
        f"{context_section}"
        f"Message:\n{message}\n\n"
        "JSON:"
    )


async def route_natural_intent(provider: LLMProvider, message: str, recent_context: str | None = None) -> NaturalIntent:
    if deterministic := deterministic_intent(message):
        return deterministic
    try:
        raw = await provider.complete(
            "You classify user messages into Frakir intents. Return strict JSON only.",
            build_intent_router_prompt(message, recent_context=recent_context),
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


def _compact_sheet_row_text(message: str, max_chars: int = 500) -> str:
    text = GOOGLE_SHEETS_URL_RE.sub("", message)
    text = " ".join(text.split()).strip(" :-")
    text = re.sub(r"\b(?:to|in|into)\s*$", "", text, flags=re.IGNORECASE).strip(" :-")
    add_named_row = re.match(r"add\s+(.+?)\s+rows?$", text, flags=re.IGNORECASE)
    if add_named_row:
        text = add_named_row.group(1).strip(" :-")
    else:
        text = re.sub(
            r"^(?:append|insert|add|log)\s+(?:this\s+)?(?:rows?\s+)?(?:to|in|into)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip(" :-")
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text or "Telegram update"
