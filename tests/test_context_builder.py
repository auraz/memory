from app.agent.context_builder import build_context_packet, select_focused_memories
from app.memory.cognee_store import MemoryItem


def test_context_packet_empty():
    assert build_context_packet([]) == "No relevant long-term memory found."


def test_context_packet_with_sources():
    packet = build_context_packet([MemoryItem(text="likes local-first tools", source="profile")])

    assert "Focused long-term memory" in packet
    assert "Optional background" in packet
    assert "[M1] (profile) likes local-first tools" in packet


def test_context_packet_ranks_and_caps_memory():
    memories = [
        MemoryItem(text="unrelated long project requirements " * 80, source="old"),
        MemoryItem(text="current emotion project decision", source="focused"),
    ]

    packet = build_context_packet(memories, query="emotion project", max_items=1, max_chars=240, max_item_chars=80)

    assert "current emotion project decision" in packet
    assert "unrelated long project requirements" not in packet
    assert len(packet) <= 240


def test_select_focused_memories_keeps_original_order_without_query():
    memories = [MemoryItem(text="one"), MemoryItem(text="two")]

    assert select_focused_memories(memories, max_items=1) == [memories[0]]
