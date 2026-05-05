from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from app.agent.service import AgentService
from app.agent.skills import get_skill, render_skills
from app.approvals.policy import ApprovalMode, ApprovalPolicy
from app.memory.chat_importer import ingest_chat_documents, load_chat_documents
from app.memory.audit import build_memory_audit, render_memory_audit
from app.memory.obsidian_importer import ingest_obsidian
from app.memory.obsidian_importer import iter_markdown_files
from app.settings import settings
from app.storage import ChatEventStore, ChatSettingsStore, IngestRunStore, SourceItemStore

DEFAULT_INGEST_LIMIT = 25


def create_dispatcher(
    agent: AgentService,
    approvals: ApprovalPolicy,
    ingest_runs: IngestRunStore,
    chat_settings: ChatSettingsStore,
    chat_events: ChatEventStore,
    source_items: SourceItemStore,
) -> Dispatcher:
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def start(message: Message) -> None:
        await message.answer("Personal memory agent is running locally.")

    @dp.message(Command("approvals"))
    async def show_approvals(message: Message) -> None:
        await message.answer(approvals.render())

    @dp.message(Command("set_approval"))
    async def set_approval(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) != 3:
            await message.answer("Usage: /set_approval <tool.name> <allow|require_approval|deny>")
            return
        _, tool_name, mode_raw = parts
        try:
            mode = ApprovalMode(mode_raw)
        except ValueError:
            await message.answer("Mode must be one of: allow, require_approval, deny")
            return
        approvals.set_mode(tool_name, mode)
        await message.answer(f"{tool_name}: {mode.value}")

    @dp.message(Command("recall"))
    async def recall(message: Message) -> None:
        query = (message.text or "").replace("/recall", "", 1).strip()
        if not query:
            await message.answer("Usage: /recall <topic>")
            return
        memories, error = await agent.memory.safe_recall(query)
        if error:
            await message.answer(f"Memory recall failed:\n{error}")
            return
        if not memories:
            await message.answer("No relevant memory found.")
            return
        body = "\n\n".join(f"- {item.text}" for item in memories)
        await message.answer(body[:3900])

    @dp.message(Command("context"))
    async def context(message: Message) -> None:
        query = (message.text or "").replace("/context", "", 1).strip()
        if not query:
            await message.answer("Usage: /context <message to inspect>")
            return
        selected = chat_settings.get(str(message.chat.id)).skill_name
        today_context = chat_events.today_context(str(message.chat.id))
        preview = await agent.preview_context(query, skill_name=selected, today_context=today_context)
        skill = preview.selected_skill or "none"
        recall = f"failed: {preview.recall_error}" if preview.recall_error else "ok"
        await message.answer(
            (
                "Context preview\n"
                f"Skill: {skill}\n"
                f"Recall: {recall}\n\n"
                f"{preview.today_context}\n\n"
                f"{preview.context_packet}"
            )[:3900]
        )

    @dp.message(Command("memory_status"))
    async def memory_status(message: Message) -> None:
        durability = "durable" if agent.memory.is_durable else "not durable; lost on restart"
        await message.answer(
            f"Memory backend: {agent.memory.backend_name}\n"
            f"Status: {durability}\n"
            f"Storage: {agent.memory.storage_path}"
        )

    @dp.message(Command("memory_audit"))
    async def memory_audit(message: Message) -> None:
        audit = build_memory_audit(agent.memory, ingest_runs, source_items)
        await message.answer(render_memory_audit(audit)[:3900])

    @dp.message(Command("skills"))
    async def skills(message: Message) -> None:
        current = chat_settings.get(str(message.chat.id)).skill_name or "off"
        await message.answer(f"{render_skills()}\n\nCurrent: {current}")

    @dp.message(Command("skill"))
    async def skill(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("Usage: /skill <name|auto|off>")
            return
        requested = parts[1].strip().lower()
        if requested == "auto":
            chat_settings.set_skill(str(message.chat.id), "auto")
            await message.answer("Skill mode: auto")
            return
        if requested == "off":
            chat_settings.set_skill(str(message.chat.id), None)
            await message.answer("Skill mode off.")
            return
        selected = get_skill(requested)
        if selected is None:
            await message.answer(f"Unknown skill: {requested}\n\n{render_skills()}")
            return
        chat_settings.set_skill(str(message.chat.id), selected.name)
        await message.answer(f"Skill mode: {selected.name}\n{selected.summary}")

    @dp.message(Command("reset_memory"))
    async def reset_memory(message: Message) -> None:
        if (message.text or "").strip() != "/reset_memory confirm":
            await message.answer("Usage: /reset_memory confirm")
            return
        if not approvals.is_allowed("memory.reset"):
            await message.answer("memory.reset is not allowed by policy. Temporarily set it to allow first.")
            return
        await message.answer("Resetting Cognee memory and ingest manifest.")
        await agent.memory.reset()
        ingest_runs.clear_manifest()
        await message.answer("Memory reset complete. Re-run /ingest_obsidian all.")

    @dp.message(Command("remember"))
    async def remember(message: Message) -> None:
        text = (message.text or "").replace("/remember", "", 1).strip()
        if not text:
            await message.answer("Usage: /remember <text>")
            return
        await message.answer(await agent.propose_memory_write(text))

    @dp.message(Command("pending"))
    async def pending(message: Message) -> None:
        await message.answer(agent.render_pending()[:3900])

    @dp.message(Command("openclaw"))
    async def openclaw(message: Message) -> None:
        text = (message.text or "").replace("/openclaw", "", 1).strip()
        if not text:
            await message.answer("Usage: /openclaw <task for OpenClaw>")
            return
        await message.answer(await agent.propose_openclaw_task(text, telegram_chat_id=str(message.chat.id)))

    @dp.message(Command("approve"))
    async def approve(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2 or not parts[1].isdigit():
            await message.answer("Usage: /approve <id>")
            return
        await message.answer(await agent.approve_action(int(parts[1])))

    @dp.message(Command("deny"))
    async def deny(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2 or not parts[1].isdigit():
            await message.answer("Usage: /deny <id>")
            return
        await message.answer(agent.deny_action(int(parts[1])))

    @dp.message(Command("ingest_obsidian"))
    async def ingest(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        limit = DEFAULT_INGEST_LIMIT
        ingest_all = False
        if len(parts) == 2:
            arg = parts[1].strip().lower()
            if arg == "all":
                limit = None
                ingest_all = True
            elif arg.isdigit():
                limit = int(arg)
            else:
                await message.answer("Usage: /ingest_obsidian [limit|all]")
                return
        scope = (
            f"all pending notes in batches of {DEFAULT_INGEST_LIMIT}"
            if ingest_all
            else f"up to {limit} notes"
        )
        await message.answer(f"Starting Obsidian ingest for {scope}.")
        run_id = None
        last_reported = 0
        completed_before_batch = 0

        async def progress(processed: int, total: int, note_path) -> None:
            nonlocal last_reported
            overall_processed = completed_before_batch + processed
            if run_id is not None:
                ingest_runs.update(run_id, overall_processed, str(note_path))
                ingest_runs.mark_file_completed(note_path, run_id)
            should_report = overall_processed == total or overall_processed - last_reported >= 25
            if should_report:
                last_reported = overall_processed
                await message.answer(f"Ingest progress: {overall_processed}/{total}\nLast: {note_path.name}")

        async def failure(processed: int, total: int, note_path, exc: Exception) -> None:
            nonlocal last_reported
            overall_processed = completed_before_batch + processed
            error = f"{type(exc).__name__}: {exc}"
            if run_id is not None:
                ingest_runs.update(run_id, overall_processed, f"FAILED {note_path}: {error}")
                ingest_runs.mark_file_failed(note_path, run_id, error)
            should_report = overall_processed == total or overall_processed - last_reported >= 25
            if should_report:
                last_reported = overall_processed
                await message.answer(
                    f"Ingest progress: {overall_processed}/{total}\n"
                    f"Skipped failed file: {note_path.name}\n"
                    f"{error[:500]}"
                )

        try:
            all_files = iter_markdown_files(settings.obsidian_vault_path)
            pending_files = [path for path in all_files if not ingest_runs.is_file_terminal(path)]
            selected_files = pending_files if limit is None else pending_files[:limit]
            if not selected_files:
                await message.answer(f"All {len(all_files)} markdown notes are already marked processed.")
                return
            total_files = len(selected_files)
            if limit is not None:
                total_files = min(total_files, len(selected_files))
            run_id = ingest_runs.start(str(settings.obsidian_vault_path), total_files)
            count = 0
            batch_size = DEFAULT_INGEST_LIMIT if ingest_all else len(selected_files)
            for start in range(0, len(selected_files), batch_size):
                batch = selected_files[start : start + batch_size]
                completed_before_batch = count
                count += await ingest_obsidian(
                    settings.obsidian_vault_path,
                    agent.memory,
                    limit=None,
                    progress=progress,
                    failure=failure,
                    note_paths=batch,
                    skip_errors=True,
                )
            failed = ingest_runs.failed_count()
            status = "completed_with_failures" if failed else "completed"
            ingest_runs.finish(run_id, status, f"Ingested {count} notes. Failed files: {failed}.")
        except Exception as exc:
            if run_id is not None:
                ingest_runs.finish(run_id, "failed", str(exc))
            await message.answer(f"Obsidian ingest failed: {exc}")
            return
        durability = "durably indexed" if agent.memory.is_durable else "loaded into volatile memory only"
        await message.answer(
            f"Ingested {count} markdown notes read-only.\n"
            f"Failed files: {ingest_runs.failed_count()}.\n"
            f"Backend: {agent.memory.backend_name} ({durability})."
        )

    @dp.message(Command("ingest_status"))
    async def ingest_status(message: Message) -> None:
        run = ingest_runs.latest()
        if run is None:
            await message.answer("No ingest runs yet.")
            return
        await message.answer(
            f"Ingest #{run.id}: {run.status}\n"
            f"Progress: {run.processed_files}/{run.total_files}\n"
            f"Completed files: {ingest_runs.completed_count()}\n"
            f"Failed files: {ingest_runs.failed_count()}\n"
            f"Processed files: {ingest_runs.terminal_count()}\n"
            f"Last update: {run.updated_at}\n"
            f"Last: {run.message or '-'}"
        )

    @dp.message(Command("ingest_source"))
    async def ingest_source(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 2:
            await message.answer("Usage: /ingest_source <chatgpt|claude|openclaw> [limit|all]")
            return
        source = parts[1].strip().lower()
        export_path = _source_path(source)
        if export_path is None:
            await message.answer(f"No export path configured for {source}.")
            return
        limit = 25
        if len(parts) == 3:
            arg = parts[2].strip().lower()
            if arg == "all":
                limit = None
            elif arg.isdigit():
                limit = int(arg)
            else:
                await message.answer("Usage: /ingest_source <chatgpt|claude|openclaw> [limit|all]")
                return
        try:
            docs = load_chat_documents(source, export_path)
        except Exception as exc:
            await message.answer(f"Failed to load {source} export: {type(exc).__name__}: {exc}")
            return
        pending = [doc for doc in docs if not source_items.is_terminal(doc.source, doc.item_id, doc.fingerprint)]
        selected = pending if limit is None else pending[:limit]
        if not selected:
            await message.answer(f"All {len(docs)} {source} conversations are already processed.")
            return
        await message.answer(f"Starting {source} ingest: {len(selected)}/{len(pending)} pending conversations.")
        ingested = 0
        failed = 0
        for index, doc in enumerate(selected, start=1):
            done, failed_one = await ingest_chat_documents([doc], agent.memory)
            if done:
                source_items.mark(doc.source, doc.item_id, doc.fingerprint, "completed")
                ingested += 1
            else:
                source_items.mark(doc.source, doc.item_id, doc.fingerprint, "failed", "Memory ingest failed")
                failed += failed_one or 1
            if index == len(selected) or index % 25 == 0:
                await message.answer(f"{source} ingest progress: {index}/{len(selected)}")
        await message.answer(
            f"{source} ingest complete.\n"
            f"Ingested: {ingested}\n"
            f"Failed: {failed}\n"
            f"Total processed for source: {source_items.count(source)}"
        )

    @dp.message(F.text)
    async def chat(message: Message) -> None:
        assert message.text is not None
        chat_id = str(message.chat.id)
        selected = chat_settings.get(str(message.chat.id)).skill_name
        today_context = chat_events.today_context(chat_id)
        response = await agent.respond(message.text, skill_name=selected, today_context=today_context)
        chat_events.append(chat_id, "user", message.text)
        chat_events.append(chat_id, "assistant", response)
        await message.answer(response[:3900])

    return dp


async def run_bot(
    agent: AgentService,
    approvals: ApprovalPolicy,
    ingest_runs: IngestRunStore,
    chat_settings: ChatSettingsStore,
    chat_events: ChatEventStore,
    source_items: SourceItemStore,
) -> None:
    if not settings.telegram_bot_token_frakir:
        raise RuntimeError("TELEGRAM_BOT_TOKEN_FRAKIR is required")
    bot = Bot(token=settings.telegram_bot_token_frakir)
    dp = create_dispatcher(agent, approvals, ingest_runs, chat_settings, chat_events, source_items)
    print("Frakir Telegram bot is running. Press Ctrl+C to stop.", flush=True)
    await dp.start_polling(bot)


def _source_path(source: str):
    if source == "chatgpt":
        return settings.chatgpt_export_path
    if source == "claude":
        return settings.claude_export_path
    if source == "openclaw":
        return settings.openclaw_export_path
    return None
