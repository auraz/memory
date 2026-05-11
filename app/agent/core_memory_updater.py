import json
import re

from app.agent.core_memory import CoreMemoryBlock, DEFAULT_BLOCKS


AUTO_UPDATE_TRIGGERS = (
    "i prefer",
    "i like",
    "i don't like",
    "i do not like",
    "do not",
    "don't",
    "remember",
    "my preference",
    "my project",
    "current focus",
    "active project",
    "i want",
    "i need",
    "i am",
    "i'm",
)


def should_consider_core_memory_update(message: str) -> bool:
    normalized = " ".join(message.lower().split())
    if len(normalized) < 12 or normalized.endswith("?"):
        return False
    return any(trigger in normalized for trigger in AUTO_UPDATE_TRIGGERS)


def build_core_memory_update_payload(blocks: list[CoreMemoryBlock], message: str) -> str:
    current = []
    for block in blocks:
        if block.label in DEFAULT_BLOCKS:
            current.append(
                f"<{block.label} limit={block.char_limit}>\n"
                f"{block.value.strip() or '(empty)'}\n"
                f"</{block.label}>"
            )
    return (
        "Update Frakir's core memory only if the user message contains a durable fact, preference, "
        "active project, or current focus that should shape future answers.\n"
        "Do not store one-off task details, imported document content, archive recall, or transient wording.\n"
        "Return strict JSON only, with full replacement values for changed blocks.\n"
        "Allowed block labels: human, persona, active_projects, preferences, current_focus.\n"
        "If nothing should change, return {\"updates\": {}}.\n\n"
        "Current core memory:\n"
        f"{chr(10).join(current)}\n\n"
        "User message:\n"
        f"{message}\n\n"
        "JSON:"
    )


def parse_core_memory_updates(raw: str) -> dict[str, str]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = json.loads(_extract_json_object(raw))
    updates = data.get("updates", {}) if isinstance(data, dict) else {}
    if not isinstance(updates, dict):
        return {}

    parsed: dict[str, str] = {}
    for label, value in updates.items():
        normalized_label = str(label).strip().lower()
        if normalized_label not in DEFAULT_BLOCKS or not isinstance(value, str):
            continue
        cleaned = " ".join(value.split())
        if cleaned:
            parsed[normalized_label] = cleaned
    return parsed


def _extract_json_object(raw: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise json.JSONDecodeError("No JSON object found", raw, 0)
    return raw[start : end + 1]
