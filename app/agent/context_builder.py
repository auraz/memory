from app.memory.cognee_store import MemoryItem


def build_context_packet(memories: list[MemoryItem]) -> str:
    if not memories:
        return "No relevant long-term memory found."
    lines = ["Relevant long-term memory:"]
    for index, item in enumerate(memories, start=1):
        source = f" ({item.source})" if item.source else ""
        lines.append(f"[M{index}]{source} {item.text}")
    return "\n".join(lines)
