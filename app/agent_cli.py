import argparse
import asyncio
import sqlite3

from app.agent import AgentService
from app.agent.core_memory import CoreMemory, SQLiteCoreMemory
from app.agent.letta_adapter import LettaCoreMemory
from app.approvals import ApprovalPolicy, ApprovalQueue
from app.memory import CogneeMemory
from app.providers import create_provider
from app.settings import settings
from app.storage import connect, init_db


def parse_message_parts(parts: list[str]) -> str:
    if parts and parts[0] == "--":
        parts = parts[1:]
    return " ".join(parts).strip()


def build_core_memory(conn: sqlite3.Connection) -> CoreMemory:
    local_core_memory = SQLiteCoreMemory(conn)
    if settings.letta_enabled and settings.letta_agent_id:
        return LettaCoreMemory(
            agent_id=settings.letta_agent_id,
            api_key=settings.letta_api_key,
            base_url=settings.letta_base_url,
            fallback=local_core_memory,
        )
    return local_core_memory


def build_agent(conn: sqlite3.Connection) -> AgentService:
    return AgentService(
        provider=create_provider(settings),
        memory=CogneeMemory(max_items=settings.max_context_items),
        approvals=ApprovalPolicy(settings.approval_policy_path),
        queue=ApprovalQueue(conn),
        core_memory=build_core_memory(conn),
    )


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Run one Frakir agent turn from the terminal.")
    parser.add_argument("--dry-run", action="store_true", help="Print the parsed request without calling the LLM.")
    parser.add_argument("--context", action="store_true", help="Preview context instead of answering.")
    parser.add_argument("--goal", action="store_true", help="Show the active goal.")
    parser.add_argument("--goal-status", action="store_true", help="Show active goal status and next step.")
    parser.add_argument("--set-goal", help="Set the active goal.")
    parser.add_argument("--clear-goal", action="store_true", help="Clear the active goal.")
    parser.add_argument("--skill", default="auto", help="Answer skill for normal turns. Defaults to auto.")
    parser.add_argument("message", nargs=argparse.REMAINDER, help="Message after --, for example: agent -- hello")
    args = parser.parse_args()

    message = parse_message_parts(args.message)
    if args.dry_run:
        action = "answer"
        if args.context:
            action = "context"
        elif args.goal:
            action = "goal"
        elif args.goal_status:
            action = "goal-status"
        elif args.set_goal:
            action = "set-goal"
        elif args.clear_goal:
            action = "clear-goal"
        print(f"Agent CLI dry run: action={action} message={message or '-'}")
        return

    init_db(settings.sqlite_path)
    with connect(settings.sqlite_path) as conn:
        agent = build_agent(conn)
        today_context = "CLI one-shot turn; no Telegram chat history."
        if args.set_goal is not None:
            print(await agent.set_goal(args.set_goal))
            return
        if args.clear_goal:
            print(await agent.clear_goal())
            return
        if args.goal:
            print(await agent.render_goal())
            return
        if args.goal_status:
            print(await agent.goal_status(message, today_context=today_context))
            return
        if not message:
            parser.error("message is required unless using --goal, --set-goal, --clear-goal, or --goal-status")
        if args.context:
            preview = await agent.preview_context(message, skill_name=args.skill, today_context=today_context)
            skill = preview.selected_skill or "none"
            recall = f"failed: {preview.recall_error}" if preview.recall_error else "ok"
            print(
                "Context preview\n"
                f"Skill: {skill}\n"
                f"Recall: {recall}\n\n"
                f"{preview.core_memory}\n\n"
                f"{preview.today_context}\n\n"
                f"{preview.context_packet}"
            )
            return
        print(await agent.respond(message, skill_name=args.skill, today_context=today_context))


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
