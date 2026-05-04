from app.agent.context_builder import build_context_packet
from app.memory.cognee_store import MemoryItem


def test_context_packet_empty():
    assert build_context_packet([]) == "No relevant long-term memory found."


def test_context_packet_with_sources():
    packet = build_context_packet([MemoryItem(text="likes local-first tools", source="profile")])

    assert "Relevant long-term memory" in packet
    assert "[M1] (profile) likes local-first tools" in packet
