from dataclasses import dataclass

from app.agent.context_builder import build_context_packet
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.skills import get_skill, select_auto_skill
from app.approvals.policy import ApprovalPolicy
from app.approvals.queue import ApprovalQueue, PendingAction
from app.memory.cognee_store import CogneeMemory
from app.providers.base import LLMProvider


@dataclass(frozen=True)
class ContextPreview:
    message: str
    context_packet: str
    today_context: str
    selected_skill: str | None
    recall_error: str | None = None


class AgentService:
    def __init__(
        self,
        provider: LLMProvider,
        memory: CogneeMemory,
        approvals: ApprovalPolicy,
        queue: ApprovalQueue,
    ):
        self.provider = provider
        self.memory = memory
        self.approvals = approvals
        self.queue = queue

    async def respond(
        self,
        message: str,
        skill_name: str | None = None,
        today_context: str | None = None,
    ) -> str:
        preview = await self.preview_context(message, skill_name=skill_name, today_context=today_context)
        skill = get_skill(preview.selected_skill)
        system_prompt = SYSTEM_PROMPT
        if skill is not None:
            system_prompt = f"{SYSTEM_PROMPT}\n\n{skill.instructions}"

        skill_line = f"Selected answer skill: {skill.name}" if skill is not None else "Selected answer skill: none"
        user_payload = (
            f"{preview.today_context}\n\n"
            f"{preview.context_packet}\n\n"
            f"{skill_line}\n\n"
            f"User message:\n{message}"
        )
        return await self.provider.complete(system_prompt, user_payload)

    async def preview_context(
        self,
        message: str,
        skill_name: str | None = None,
        today_context: str | None = None,
    ) -> ContextPreview:
        if self.approvals.is_denied("memory.recall"):
            context_packet = "Long-term memory recall is denied by policy."
            recall_error = None
        else:
            memories, error = await self.memory.safe_recall(message)
            if error:
                context_packet = f"Long-term memory recall failed: {error}"
                recall_error = error
            else:
                context_packet = build_context_packet(memories)
                recall_error = None
        resolved_skill_name = select_auto_skill(message) if skill_name == "auto" else skill_name
        skill = get_skill(resolved_skill_name)
        return ContextPreview(
            message=message,
            context_packet=context_packet,
            today_context=today_context or "No prior Telegram messages with the bot today.",
            selected_skill=skill.name if skill is not None else None,
            recall_error=recall_error,
        )

    async def propose_memory_write(self, text: str) -> str:
        mode = self.approvals.mode_for("memory.write")
        if mode.value == "allow":
            await self.memory.remember(text, source="telegram")
            return "Stored."
        if mode.value == "deny":
            return "Memory writes are denied by policy."
        action_id = self.queue.create("memory.write", {"text": text, "source": "telegram"})
        return f"Queued memory write #{action_id}.\nUse /approve {action_id} or /deny {action_id}."

    async def approve_action(self, action_id: int) -> str:
        action = self.queue.get_pending(action_id)
        if action is None:
            return f"No pending action #{action_id}."
        result = await self._execute_approved(action)
        self.queue.mark(action_id, "approved")
        return result

    def deny_action(self, action_id: int) -> str:
        action = self.queue.get_pending(action_id)
        if action is None:
            return f"No pending action #{action_id}."
        self.queue.mark(action_id, "denied")
        return f"Denied action #{action_id}."

    def render_pending(self) -> str:
        actions = self.queue.list_pending()
        if not actions:
            return "No pending actions."
        lines: list[str] = []
        for action in actions:
            summary = action.payload.get("text") or str(action.payload)
            lines.append(f"#{action.id} {action.tool_name}: {summary}")
        return "\n".join(lines)

    async def _execute_approved(self, action: PendingAction) -> str:
        if action.tool_name == "memory.write":
            await self.memory.remember(
                str(action.payload["text"]),
                source=str(action.payload.get("source", "telegram")),
            )
            return f"Approved and stored memory #{action.id}."
        return f"Action #{action.id} has no executor yet: {action.tool_name}"
