from dataclasses import dataclass
from pathlib import Path

from app.agent.context_builder import build_context_packet
from app.agent.core_memory import CoreMemory
from app.agent.core_memory_updater import (
    build_core_memory_update_payload,
    parse_core_memory_updates,
    should_consider_core_memory_update,
)
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.skills import build_skill_router_prompt, get_skill, parse_skill_router_output, select_auto_skill
from app.approvals.policy import ApprovalPolicy
from app.approvals.queue import ApprovalQueue, PendingAction
from app.memory.cognee_store import CogneeMemory
from app.memory.palace import append_palace_memory
from app.providers.base import LLMProvider
from app.settings import settings
from app.tools import gws
from app.tools import run_openclaw_agent

ACTIVE_GOAL_BLOCK = "active_goal"
ACTIVE_GOAL_DESCRIPTION = "The single active goal Frakir should keep in view across normal answers and tool routing."


@dataclass(frozen=True)
class ContextPreview:
    message: str
    core_memory: str
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
        core_memory: CoreMemory | None = None,
        memory_palace_dir: Path | None = None,
    ):
        self.provider = provider
        self.memory = memory
        self.approvals = approvals
        self.queue = queue
        self.core_memory = core_memory
        self.memory_palace_dir = memory_palace_dir or settings.obsidian_vault_path / "Frakir Palace"

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
            system_prompt = f"{SYSTEM_PROMPT}\n\n{skill.prompt()}"

        skill_line = f"Selected answer skill: {skill.name}" if skill is not None else "Selected answer skill: none"
        user_payload = (
            f"{preview.core_memory}\n\n"
            f"{preview.today_context}\n\n"
            f"{preview.context_packet}\n\n"
            f"{skill_line}\n\n"
            f"User message:\n{message}"
        )
        response = await self.provider.complete(system_prompt, user_payload)
        await self.auto_update_core_memory(message)
        return response

    async def preview_context(
        self,
        message: str,
        skill_name: str | None = None,
        today_context: str | None = None,
    ) -> ContextPreview:
        core_memory = await self.core_memory.render(settings.core_memory_chars) if self.core_memory else "Core memory disabled."
        resolved_skill_name = await self.resolve_skill_name(message, skill_name)
        skill = get_skill(resolved_skill_name)
        if self.approvals.is_denied("memory.recall"):
            context_packet = "Long-term memory recall is denied by policy."
            recall_error = None
        else:
            memories, error = await self.memory.safe_recall(message)
            if error:
                context_packet = f"Long-term memory recall failed: {error}"
                recall_error = error
            else:
                context_packet = build_context_packet(
                    memories,
                    query=message,
                    max_items=skill.max_memory_items if skill else settings.focused_context_items,
                    max_chars=skill.max_memory_chars if skill else settings.focused_context_chars,
                    max_item_chars=skill.max_item_chars if skill else settings.focused_memory_item_chars,
                )
                recall_error = None
        return ContextPreview(
            message=message,
            core_memory=core_memory,
            context_packet=context_packet,
            today_context=today_context or "No prior Telegram messages with the bot today.",
            selected_skill=skill.name if skill is not None else None,
            recall_error=recall_error,
        )

    async def resolve_skill_name(self, message: str, skill_name: str | None) -> str | None:
        if skill_name != "auto":
            return skill_name
        try:
            raw = await self.provider.complete(
                "You route messages to answer skills. Return only the skill name.",
                build_skill_router_prompt(message),
            )
            selected = parse_skill_router_output(raw)
            if selected is not None:
                return selected
        except Exception:
            pass
        return select_auto_skill(message)

    async def render_core_memory(self) -> str:
        if self.core_memory is None:
            return "Core memory disabled."
        return await self.core_memory.render(settings.core_memory_chars)

    async def set_core_memory(self, label: str, value: str) -> str:
        if self.core_memory is None:
            return "Core memory disabled."
        await self.core_memory.set_block(label, value)
        return f"Updated core memory block: {label}"

    async def get_goal(self) -> str:
        if self.core_memory is None:
            return ""
        for block in await self.core_memory.list_blocks():
            if block.label == ACTIVE_GOAL_BLOCK:
                return block.value.strip()
        return ""

    async def set_goal(self, text: str) -> str:
        if self.core_memory is None:
            return "Core memory disabled."
        goal = " ".join(text.split())
        if not goal:
            return "Goal cannot be empty."
        await self.core_memory.set_block(
            ACTIVE_GOAL_BLOCK,
            goal,
            description=ACTIVE_GOAL_DESCRIPTION,
            char_limit=1200,
        )
        return f"Active goal set:\n{goal}"

    async def clear_goal(self) -> str:
        if self.core_memory is None:
            return "Core memory disabled."
        await self.core_memory.set_block(
            ACTIVE_GOAL_BLOCK,
            "",
            description=ACTIVE_GOAL_DESCRIPTION,
            char_limit=1200,
        )
        return "Active goal cleared."

    async def render_goal(self) -> str:
        goal = await self.get_goal()
        if not goal:
            return "No active goal set."
        return f"Active goal:\n{goal}"

    async def goal_status(self, message: str = "", today_context: str | None = None) -> str:
        goal = await self.get_goal()
        if not goal:
            return "No active goal set."
        query = message.strip() or f"Goal status and next step for: {goal}"
        preview = await self.preview_context(query, skill_name="planner", today_context=today_context)
        payload = (
            f"{preview.core_memory}\n\n"
            f"{preview.today_context}\n\n"
            f"{preview.context_packet}\n\n"
            f"Active goal:\n{goal}\n\n"
            "Return a concise goal status with:\n"
            "- current goal\n"
            "- next concrete step\n"
            "- why this step matters\n"
            "- blocker or risk, if any\n"
        )
        return await self.provider.complete(
            "You are Frakir. Be concise, pragmatic, and action-oriented.",
            payload,
        )

    async def auto_update_core_memory(self, message: str) -> list[str]:
        if self.core_memory is None or not settings.core_memory_auto_update:
            return []
        if not should_consider_core_memory_update(message):
            return []

        blocks = await self.core_memory.list_blocks()
        payload = build_core_memory_update_payload(blocks, message)
        try:
            raw = await self.provider.complete(
                "You are a precise memory curator. Return strict JSON only.",
                payload,
            )
            updates = parse_core_memory_updates(raw)
        except Exception:
            return []

        updated: list[str] = []
        for label, value in updates.items():
            await self.core_memory.set_block(label, value)
            updated.append(label)
        return updated

    async def propose_memory_write(self, text: str) -> str:
        mode = self.approvals.mode_for("memory.write")
        if mode.value == "allow":
            return await self._store_memory_write(text)
        if mode.value == "deny":
            return "Memory writes are denied by policy."
        action_id = self.queue.create("memory.write", {"text": text, "source": "palace:remember"})
        return f"Queued memory write #{action_id}.\nUse /approve {action_id} or /deny {action_id}."

    async def propose_openclaw_task(self, text: str, telegram_chat_id: str) -> str:
        payload = {
            "message": prepare_openclaw_message(text),
            "session_id": f"frakir-telegram-{telegram_chat_id}",
        }
        mode = self.approvals.mode_for("openclaw.agent_send")
        if mode.value == "allow":
            return await self._run_openclaw(payload)
        if mode.value == "deny":
            return "OpenClaw delegation is denied by policy."
        action_id = self.queue.create("openclaw.agent_send", payload)
        return (
            f"Queued OpenClaw task #{action_id}.\n"
            f"Message: {text}\n"
            f"Use /approve {action_id} or /deny {action_id}."
        )

    async def propose_gws_sheets_action(self, tool_name: str, payload: dict) -> str:
        return await self._run_gws_sheets_action(tool_name, payload)

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
            result = await self._store_memory_write(str(action.payload["text"]))
            return f"Approved memory #{action.id}.\n{result}"
        if action.tool_name == "openclaw.agent_send":
            return await self._run_openclaw(action.payload)
        if action.tool_name.startswith("gws.sheets."):
            return await self._run_gws_sheets_action(action.tool_name, action.payload)
        return f"Action #{action.id} has no executor yet: {action.tool_name}"

    async def _store_memory_write(self, text: str) -> str:
        path = append_palace_memory(text, self.memory_palace_dir)
        source = f"palace:remember:{path.stem}"
        try:
            await self.memory.remember(f"Remembered in Frakir Palace ({path.name}): {text}", source=source)
        except Exception as exc:
            return f"Stored in memory palace: {path}\nCognee indexing failed: {type(exc).__name__}: {exc}"
        return f"Stored in memory palace: {path}\nIndexed in Cognee source: {source}"

    async def _run_openclaw(self, payload: dict) -> str:
        result = await run_openclaw_agent(
            message=str(payload["message"]),
            session_id=str(payload["session_id"]),
            cli_path=settings.openclaw_cli_path,
            agent_id=settings.openclaw_agent_id,
            local=settings.openclaw_local,
            timeout_seconds=settings.openclaw_timeout_seconds,
        )
        return f"OpenClaw result:\n{result.text}"

    async def _run_gws_sheets_action(self, tool_name: str, payload: dict) -> str:
        if tool_name == "gws.sheets.create":
            result = await gws_create_spreadsheet(str(payload.get("title") or ""), payload.get("rows") or [])
        elif tool_name == "gws.sheets.read":
            result = await gws_read_range(str(payload.get("spreadsheet_id") or ""), str(payload.get("range") or ""))
        elif tool_name == "gws.sheets.update":
            result = await gws_update_range(
                str(payload.get("spreadsheet_id") or ""),
                str(payload.get("range") or ""),
                payload.get("values") or [],
            )
        elif tool_name == "gws.sheets.append":
            result = await gws_append_rows(
                str(payload.get("spreadsheet_id") or ""),
                str(payload.get("worksheet") or "Sheet1"),
                payload.get("rows") or [],
            )
        elif tool_name == "gws.sheets.replace":
            result = await gws_replace_worksheet(
                str(payload.get("spreadsheet_id") or ""),
                str(payload.get("worksheet") or ""),
                payload.get("rows") or [],
            )
        elif tool_name == "gws.sheets.fill_column":
            result = await gws_fill_column(
                str(payload.get("spreadsheet_id") or ""),
                str(payload.get("worksheet") or ""),
                str(payload.get("header") or ""),
                payload.get("value"),
            )
        else:
            return f"Unknown Google Workspace action: {tool_name}"
        return result.render()


def prepare_openclaw_message(text: str) -> str:
    request = text.strip()
    if not request:
        return request
    lower = request.lower()
    explicit_web_markers = ("search", "internet", "web", "browse", "look up", "website", "source")
    local_markers = ("local", "logs", "files", "workspace", "repo", "disk")
    if any(marker in lower for marker in local_markers) and not any(marker in lower for marker in explicit_web_markers):
        return request
    web_markers = (
        "search",
        "internet",
        "web",
        "browse",
        "look up",
        "latest",
        "current",
        "website",
        "source",
    )
    if not any(marker in lower for marker in web_markers):
        return request
    return (
        "Use web search/browser tools for this request. Do not answer from local files or memory unless the user "
        "explicitly asks for local inspection. Answer in English unless the user's request is in another language. "
        "Cite the sources you used with links. Keep the answer concise.\n\n"
        f"User request:\n{request}"
    )


async def gws_create_spreadsheet(title: str, rows: object) -> gws.GwsSheetsResult:
    import asyncio

    if _use_gws_mcp_backend():
        from app.tools import gws_mcp

        return await gws_mcp.create_spreadsheet(title, rows)  # type: ignore[arg-type]
    return await asyncio.to_thread(gws.create_spreadsheet, title, rows)


async def gws_read_range(spreadsheet_id: str, range_name: str) -> gws.GwsSheetsResult:
    import asyncio

    if _use_gws_mcp_backend():
        from app.tools import gws_mcp

        return await gws_mcp.read_range(spreadsheet_id, range_name)
    return await asyncio.to_thread(gws.read_range, spreadsheet_id, range_name)


async def gws_update_range(spreadsheet_id: str, range_name: str, values: object) -> gws.GwsSheetsResult:
    import asyncio

    if _use_gws_mcp_backend():
        from app.tools import gws_mcp

        return await gws_mcp.update_range(spreadsheet_id, range_name, values)  # type: ignore[arg-type]
    return await asyncio.to_thread(gws.update_range, spreadsheet_id, range_name, values)


async def gws_append_rows(spreadsheet_id: str, worksheet: str, rows: object) -> gws.GwsSheetsResult:
    import asyncio

    if _use_gws_mcp_backend():
        from app.tools import gws_mcp

        return await gws_mcp.append_rows(spreadsheet_id, worksheet, rows)  # type: ignore[arg-type]
    return await asyncio.to_thread(gws.append_rows, spreadsheet_id, worksheet, rows)


async def gws_replace_worksheet(spreadsheet_id: str, worksheet: str, rows: object) -> gws.GwsSheetsResult:
    import asyncio

    if _use_gws_mcp_backend():
        from app.tools import gws_mcp

        return await gws_mcp.replace_worksheet(spreadsheet_id, worksheet, rows)  # type: ignore[arg-type]
    return await asyncio.to_thread(gws.replace_worksheet, spreadsheet_id, worksheet, rows)


async def gws_fill_column(spreadsheet_id: str, worksheet: str, header: str, value: object) -> gws.GwsSheetsResult:
    import asyncio

    if _use_gws_mcp_backend():
        from app.tools import gws_mcp

        return await gws_mcp.fill_column(spreadsheet_id, worksheet, header, value)
    return await asyncio.to_thread(gws.fill_column, spreadsheet_id, worksheet, header, value)


def _use_gws_mcp_backend() -> bool:
    return settings.gws_backend.strip().lower() in {"mcp", "mcp_stdio", "workspace_mcp"}
