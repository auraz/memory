import asyncio

from app.agent.service import AgentService
from app.approvals.policy import ApprovalPolicy
from app.memory.cognee_store import MemoryItem


class FakeProvider:
    def __init__(self):
        self.system = ""
        self.user = ""

    async def complete(self, system: str, user: str) -> str:
        self.system = system
        self.user = user
        return "done"


class FakeMemory:
    async def safe_recall(self, query: str):
        return [MemoryItem(text=f"memory for {query}", source="test")], None


class FakeQueue:
    pass


def test_preview_context_shows_recalled_memory_and_auto_skill(tmp_path):
    agent = AgentService(FakeProvider(), FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), FakeQueue())

    preview = asyncio.run(agent.preview_context("what did I work on emotions?", skill_name="auto"))

    assert preview.selected_skill == "research"
    assert preview.recall_error is None
    assert "[M1] (test) memory for what did I work on emotions?" in preview.context_packet


def test_respond_sends_context_to_provider(tmp_path):
    provider = FakeProvider()
    agent = AgentService(provider, FakeMemory(), ApprovalPolicy(tmp_path / "approvals.yaml"), FakeQueue())

    response = asyncio.run(agent.respond("brainstorm ideas", skill_name="auto"))

    assert response == "done"
    assert "Skill: brainstorm" in provider.system
    assert "Relevant long-term memory" in provider.user
    assert "User message:\nbrainstorm ideas" in provider.user
