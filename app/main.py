import asyncio

from app.agent import AgentService
from app.agent.core_memory import SQLiteCoreMemory
from app.agent.letta_adapter import LettaCoreMemory
from app.approvals import ApprovalPolicy, ApprovalQueue
from app.bot.telegram import run_bot
from app.memory import CogneeMemory
from app.providers import create_provider
from app.runtime_limits import raise_file_descriptor_limit
from app.settings import settings
from app.storage import ChatEventStore, ChatSettingsStore, IngestRunStore, SourceItemStore, connect, init_db


async def _async_main() -> None:
    soft_limit, hard_limit = raise_file_descriptor_limit()
    print(f"Open file limit: soft={soft_limit} hard={hard_limit}", flush=True)
    init_db(settings.sqlite_path)
    conn = connect(settings.sqlite_path)
    approvals = ApprovalPolicy(settings.approval_policy_path)
    queue = ApprovalQueue(conn)
    ingest_runs = IngestRunStore(conn)
    chat_settings = ChatSettingsStore(conn)
    chat_events = ChatEventStore(conn)
    source_items = SourceItemStore(conn)
    provider = create_provider(settings)
    memory = CogneeMemory(max_items=settings.max_context_items)
    local_core_memory = SQLiteCoreMemory(conn)
    core_memory = local_core_memory
    if settings.letta_enabled and settings.letta_agent_id:
        core_memory = LettaCoreMemory(
            agent_id=settings.letta_agent_id,
            api_key=settings.letta_api_key,
            base_url=settings.letta_base_url,
            fallback=local_core_memory,
        )
    agent = AgentService(provider=provider, memory=memory, approvals=approvals, queue=queue, core_memory=core_memory)
    await run_bot(agent, approvals, ingest_runs, chat_settings, chat_events, source_items)


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
