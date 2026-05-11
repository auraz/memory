from app.memory.cognee_store import MemoryItem


STOPWORDS = {
    "a",
    "about",
    "all",
    "and",
    "are",
    "can",
    "did",
    "do",
    "for",
    "from",
    "get",
    "have",
    "how",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "should",
    "that",
    "the",
    "this",
    "to",
    "what",
    "when",
    "with",
    "you",
}


def build_context_packet(
    memories: list[MemoryItem],
    query: str = "",
    max_items: int = 4,
    max_chars: int = 2200,
    max_item_chars: int = 500,
) -> str:
    if not memories:
        return "No relevant long-term memory found."
    selected = select_focused_memories(memories, query=query, max_items=max_items)
    lines = [
        "Focused long-term memory:",
        "Optional background; ignore irrelevant or stale items.",
    ]
    remaining = max_chars - sum(len(line) + 1 for line in lines)
    for index, item in enumerate(selected, start=1):
        if remaining <= 0:
            break
        source = f" ({item.source})" if item.source else ""
        prefix = f"[M{index}]{source} "
        text_budget = max(0, min(max_item_chars, remaining - len(prefix)))
        if text_budget <= 0:
            break
        text = _compact_text(item.text, text_budget)
        line = f"{prefix}{text}"
        lines.append(line)
        remaining -= len(line) + 1
    return "\n".join(lines)


def select_focused_memories(
    memories: list[MemoryItem],
    query: str = "",
    max_items: int = 4,
) -> list[MemoryItem]:
    if max_items <= 0:
        return []
    query_terms = _terms(query)
    if not query_terms:
        return memories[:max_items]
    scored = [
        (index, _score_memory(item, query_terms), item)
        for index, item in enumerate(memories)
    ]
    positive = [entry for entry in scored if entry[1] > 0]
    ranked = positive or scored
    ranked.sort(key=lambda entry: (-entry[1], entry[0]))
    return [item for _index, _score, item in ranked[:max_items]]


def _score_memory(item: MemoryItem, query_terms: set[str]) -> int:
    text_terms = _terms(f"{item.source or ''} {item.text}")
    overlap = query_terms & text_terms
    score = len(overlap) * 10
    lowered = item.text.lower()
    if any(marker in lowered for marker in ["todo", "decision", "preference", "current", "next"]):
        score += 2
    if len(item.text) > 3000:
        score -= 3
    return score


def _terms(text: str) -> set[str]:
    normalized = "".join(char.lower() if char.isalnum() else " " for char in text)
    return {
        token
        for token in normalized.split()
        if len(token) > 2 and token not in STOPWORDS
    }


def _compact_text(text: str, max_chars: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(0, max_chars - 1)].rstrip() + "…"
