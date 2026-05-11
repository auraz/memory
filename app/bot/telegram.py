from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from app.agent.service import AgentService
from app.agent.skills import get_skill, render_skills
from app.agent.core_memory_seed import sync_core_memory_from_palace
from app.approvals.policy import ApprovalMode, ApprovalPolicy
from app.bot.actions import ACTION_SPECS, is_allowed_during_memory_job
from app.bot.intents import route_natural_intent
from app.bot.memory_jobs import MemoryJobQueue
from app.memory.chat_importer import ingest_chat_documents, load_chat_documents
from app.memory.audit import build_memory_audit, render_memory_audit
from app.memory.local_sources import (
    LocalMemoryDocument,
    ingest_local_memory_delta,
    ingest_local_memory_documents,
    index_local_memory_text,
    is_unchanged_by_stat,
    load_local_memory_documents,
    should_ingest_delta,
    summarize_text_with_apfel_rolling,
)
from app.memory.obsidian_importer import ingest_obsidian
from app.memory.obsidian_importer import iter_markdown_files
from app.memory.palace import build_palace
from app.settings import settings
from app.storage import ChatEventStore, ChatSettingsStore, IngestRunStore, SourceItemStore
from app.storage.ingest_runs import IngestRun
from app.tools import PKILL_TARGETS, run_pkill

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
    memory_jobs = MemoryJobQueue()

    def active_memory_job_message() -> str | None:
        active = memory_jobs.active_snapshot()
        if active is None:
            return None
        return (
            f"Memory update is running: #{active.id} {active.name}\n"
            f"Status: {active.status}\n"
            f"Last: {active.message}\n"
            "Use /memory_jobs for status or /cancel_memory_job to stop it."
        )

    async def enqueue_memory_job(message: Message, name: str, runner) -> None:
        async def wrapped_runner() -> None:
            await runner()
            await message.answer(f"Memory job complete: {name}")

        snapshot = await memory_jobs.start(name, wrapped_runner)
        if snapshot is None:
            active = active_memory_job_message()
            await message.answer(active or "A memory job is already running.")
            return
        await message.answer(f"Queued memory job #{snapshot.id}: {name}\nUse /memory_jobs for status.")

    async def run_obsidian_ingest_job(message: Message, limit: int | None, ingest_all: bool) -> None:
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
            raise
        durability = "durably indexed" if agent.memory.is_durable else "loaded into volatile memory only"
        await message.answer(
            f"Ingested {count} markdown notes read-only.\n"
            f"Failed files: {ingest_runs.failed_count()}.\n"
            f"Backend: {agent.memory.backend_name} ({durability})."
        )

    async def run_local_memory_ingest_job(message: Message, limit: int | None) -> None:
        docs = load_local_memory_documents()
        pending = []
        for doc in docs:
            record = source_items.get(doc.source, doc.item_id)
            if record and is_unchanged_by_stat(doc, record.size_bytes, record.mtime_ns):
                continue
            if source_items.is_terminal(doc.source, doc.item_id, doc.fingerprint):
                if record and not record.content_text:
                    source_items.mark(
                        doc.source,
                        doc.item_id,
                        doc.fingerprint,
                        "completed",
                        message="backfilled",
                        content_text=doc.sanitized_text,
                        size_bytes=doc.size_bytes,
                        mtime_ns=doc.mtime_ns,
                    )
                continue
            pending.append(doc)
        selected = pending if limit is None else pending[:limit]
        if not selected:
            await message.answer(f"All {len(docs)} local memory documents are already processed.")
            return
        run_id = ingest_runs.start("local_memories", len(selected))
        await message.answer(f"Starting local memory ingest: {len(selected)}/{len(pending)} pending documents.")
        ingested = 0
        failed = 0
        try:
            for index, doc in enumerate(selected, start=1):
                message_text = f"{doc.source}: {doc.title}"
                ingest_runs.update(run_id, index, message_text)
                record = source_items.get(doc.source, doc.item_id)
                mode = "new"

                async def stage_progress(stage: str) -> None:
                    stage_message = f"{message_text} ({mode}; {stage})"
                    ingest_runs.update(run_id, index, stage_message)
                    await message.answer(
                        f"Local memory ingest progress: {index}/{len(selected)}\n"
                        f"Ingested: {ingested} Failed: {failed}\n"
                        f"Last: {message_text}\n"
                        f"Stage: {stage}"
                    )

                if record and record.status == "completed" and should_ingest_delta(doc):
                    mode = "delta"
                    errors: list[str] = []
                    done, current_text = await ingest_local_memory_delta(
                        doc,
                        record.content_text,
                        agent.memory,
                        progress=stage_progress,
                        errors=errors,
                    )
                    failed_one = 0 if done or current_text == doc.sanitized_text else 1
                else:
                    errors = []
                    done, failed_one = await ingest_local_memory_documents(
                        [doc],
                        agent.memory,
                        progress=stage_progress,
                        errors=errors,
                    )
                    current_text = doc.sanitized_text
                if done:
                    source_items.mark(
                        doc.source,
                        doc.item_id,
                        doc.fingerprint,
                        "completed",
                        message=mode,
                        content_text=current_text,
                        size_bytes=doc.size_bytes,
                        mtime_ns=doc.mtime_ns,
                    )
                    ingested += 1
                elif mode == "delta" and current_text == doc.sanitized_text:
                    source_items.mark(
                        doc.source,
                        doc.item_id,
                        doc.fingerprint,
                        "completed",
                        message="delta-empty",
                        content_text=current_text,
                        size_bytes=doc.size_bytes,
                        mtime_ns=doc.mtime_ns,
                    )
                else:
                    source_items.mark(
                        doc.source,
                        doc.item_id,
                        doc.fingerprint,
                        "failed",
                        errors[0] if errors else "Local memory ingest failed",
                        content_text=record.content_text if record else "",
                        size_bytes=doc.size_bytes,
                        mtime_ns=doc.mtime_ns,
                    )
                    failed += failed_one or 1
                    await message.answer(
                        f"Local memory ingest skipped failed document: {index}/{len(selected)}\n"
                        f"{message_text}"
                    )
                if index == 1 or index == len(selected) or index % 5 == 0:
                    await message.answer(
                        f"Local memory ingest progress: {index}/{len(selected)}\n"
                        f"Ingested: {ingested} Failed: {failed}\n"
                        f"Last: {message_text} ({mode})"
                    )
        except Exception as exc:
            ingest_runs.finish(run_id, "failed", f"Local memory ingest failed: {type(exc).__name__}: {exc}")
            await message.answer(f"Local memory ingest failed: {type(exc).__name__}: {exc}")
            raise
        status = "completed_with_failures" if failed else "completed"
        ingest_runs.finish(run_id, status, f"Ingested {ingested} local memory documents. Failed: {failed}.")
        await message.answer(
            f"Local memory ingest complete.\n"
            f"Ingested: {ingested}\n"
            f"Failed: {failed}"
        )

    async def run_chat_source_ingest_job(message: Message, source: str, export_path, limit: int | None) -> None:
        try:
            docs = load_chat_documents(source, export_path)
        except Exception as exc:
            await message.answer(f"Failed to load {source} export: {type(exc).__name__}: {exc}")
            raise
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

    async def run_summary_ingest_job(message: Message, limit: int | None) -> None:
        try:
            docs = _load_non_obsidian_summary_documents()
        except Exception as exc:
            await message.answer(f"Failed to load summary inputs: {type(exc).__name__}: {exc}")
            raise
        pending = []
        for doc in docs:
            record = source_items.get(doc.source, doc.item_id)
            if record and record.status == "completed" and record.fingerprint == doc.fingerprint:
                continue
            pending.append(doc)
        selected = pending if limit is None else pending[:limit]
        if not selected:
            await message.answer(f"All {len(docs)} non-Obsidian documents are already processed.")
            return
        run_id = ingest_runs.start("apfel_summaries", len(selected))
        await message.answer(f"Starting Apfel summary ingest: {len(selected)}/{len(pending)} pending documents.")
        ingested = 0
        failed = 0
        try:
            for index, doc in enumerate(selected, start=1):
                message_text = f"{doc.source}: {doc.title}"
                ingest_runs.update(run_id, index, message_text)

                async def stage_progress(stage: str) -> None:
                    ingest_runs.update(run_id, index, f"{message_text} (apfel-summary; {stage})")
                    await message.answer(
                        f"Apfel summary ingest progress: {index}/{len(selected)}\n"
                        f"Ingested: {ingested} Failed: {failed}\n"
                        f"Last: {message_text}\n"
                        f"Stage: {stage}"
                    )

                try:
                    current_text = doc.sanitized_text
                    summary = await summarize_text_with_apfel_rolling(doc, current_text, progress=stage_progress)
                    await index_local_memory_text(doc, summary, agent.memory, progress=stage_progress)
                except Exception as exc:
                    failed += 1
                    error = f"{type(exc).__name__}: {exc}"
                    source_items.mark(
                        doc.source,
                        doc.item_id,
                        doc.fingerprint,
                        "failed",
                        error,
                        content_text=doc.sanitized_text,
                        size_bytes=doc.size_bytes,
                        mtime_ns=doc.mtime_ns,
                    )
                    await message.answer(
                        f"Apfel summary ingest skipped failed document: {index}/{len(selected)}\n"
                        f"{message_text}\n"
                        f"{error[:500]}"
                    )
                    continue
                source_items.mark(
                    doc.source,
                    doc.item_id,
                    doc.fingerprint,
                    "completed",
                    "apfel-summary",
                    content_text=current_text,
                    size_bytes=doc.size_bytes,
                    mtime_ns=doc.mtime_ns,
                )
                ingested += 1
                if index == 1 or index == len(selected) or index % 5 == 0:
                    await message.answer(
                        f"Apfel summary ingest progress: {index}/{len(selected)}\n"
                        f"Ingested: {ingested} Failed: {failed}\n"
                        f"Last: {message_text} (apfel-summary)"
                    )
        except Exception as exc:
            ingest_runs.finish(run_id, "failed", f"Apfel summary ingest failed: {type(exc).__name__}: {exc}")
            await message.answer(f"Apfel summary ingest failed: {type(exc).__name__}: {exc}")
            raise
        status = "completed_with_failures" if failed else "completed"
        ingest_runs.finish(run_id, status, f"Ingested {ingested} Apfel summaries. Failed: {failed}.")
        await message.answer(
            f"Apfel summary ingest complete.\n"
            f"Ingested: {ingested}\n"
            f"Failed: {failed}"
        )

    async def answer_memory_status(message: Message) -> None:
        durability = "durable" if agent.memory.is_durable else "not durable; lost on restart"
        core_memory = "letta" if settings.letta_enabled and settings.letta_agent_id else "local"
        await message.answer(
            f"Memory backend: {agent.memory.backend_name}\n"
            f"Status: {durability}\n"
            f"Storage: {agent.memory.storage_path}\n"
            f"Core memory: {core_memory}"
        )

    async def answer_recall(message: Message, query: str) -> None:
        query = query.strip()
        if not query:
            await message.answer("Tell me what to recall, for example: recall emotions")
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

    async def answer_context_preview(message: Message, query: str) -> None:
        query = query.strip()
        if not query:
            await message.answer("Tell me the message to inspect, for example: context for what should I focus on?")
            return
        selected = chat_settings.get(str(message.chat.id)).skill_name
        today_context = chat_events.today_context(str(message.chat.id), limit=4, max_chars=700)
        preview = await agent.preview_context(query, skill_name=selected, today_context=today_context)
        skill = preview.selected_skill or "none"
        recall = f"failed: {preview.recall_error}" if preview.recall_error else "ok"
        await message.answer(
            (
                "Context preview\n"
                f"Skill: {skill}\n"
                f"Recall: {recall}\n\n"
                f"{preview.core_memory}\n\n"
                f"{preview.today_context}\n\n"
                f"{preview.context_packet}"
            )[:3900]
        )

    async def answer_skill_mode(message: Message, requested: str) -> None:
        requested = requested.strip().lower()
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

    async def run_recall_action(message: Message, args: dict[str, Any]) -> None:
        await answer_recall(message, str(args.get("topic") or message.text or ""))

    async def run_context_preview_action(message: Message, args: dict[str, Any]) -> None:
        await answer_context_preview(message, str(args.get("message") or message.text or ""))

    async def run_show_core_memory_action(message: Message, args: dict[str, Any]) -> None:
        await message.answer((await agent.render_core_memory())[:3900])

    async def run_memory_status_action(message: Message, args: dict[str, Any]) -> None:
        await answer_memory_status(message)

    async def run_memory_jobs_action(message: Message, args: dict[str, Any]) -> None:
        await message.answer(memory_jobs.render()[:3900])

    async def run_cancel_memory_job_action(message: Message, args: dict[str, Any]) -> None:
        if memory_jobs.cancel_current():
            await message.answer("Cancellation requested for the active memory job.")
        else:
            await message.answer("No active memory job to cancel.")

    async def run_list_skills_action(message: Message, args: dict[str, Any]) -> None:
        current = chat_settings.get(str(message.chat.id)).skill_name or "off"
        await message.answer(f"{render_skills()}\n\nCurrent: {current}")

    async def run_set_skill_action(message: Message, args: dict[str, Any]) -> None:
        requested = str(args.get("skill") or "").strip().lower()
        if not requested:
            await message.answer("Tell me which skill to use, for example: use planner skill")
            return
        await answer_skill_mode(message, requested)

    async def run_refresh_memory_action(message: Message, args: dict[str, Any]) -> None:
        await enqueue_memory_job(message, "refresh_memory", lambda: run_full_refresh(message))

    async def run_remember_action(message: Message, args: dict[str, Any]) -> None:
        text = str(args.get("text") or "").strip()
        if not text:
            await message.answer("Tell me what to remember.")
            return
        await message.answer(await agent.propose_memory_write(text))

    async def run_openclaw_delegate_action(message: Message, args: dict[str, Any]) -> None:
        task = str(args.get("task") or "").strip()
        if not task:
            await message.answer("Tell me what to ask OpenClaw.")
            return
        await message.answer(await agent.propose_openclaw_task(task, telegram_chat_id=str(message.chat.id)))

    async def run_goal_action(message: Message, args: dict[str, Any]) -> None:
        operation = str(args.get("operation") or "show").strip().lower()
        text = str(args.get("text") or "").strip()
        if operation == "set":
            await message.answer(await agent.set_goal(text))
            return
        if operation == "clear":
            await message.answer(await agent.clear_goal())
            return
        if operation == "status":
            today_context = chat_events.today_context(str(message.chat.id), limit=4, max_chars=700)
            await message.answer((await agent.goal_status(message.text or "", today_context=today_context))[:3900])
            return
        await message.answer((await agent.render_goal())[:3900])

    natural_action_handlers: dict[str, Callable[[Message, dict[str, Any]], Awaitable[None]]] = {
        "recall": run_recall_action,
        "context_preview": run_context_preview_action,
        "show_core_memory": run_show_core_memory_action,
        "memory_status": run_memory_status_action,
        "memory_jobs": run_memory_jobs_action,
        "cancel_memory_job": run_cancel_memory_job_action,
        "list_skills": run_list_skills_action,
        "set_skill": run_set_skill_action,
        "refresh_memory": run_refresh_memory_action,
        "remember": run_remember_action,
        "openclaw_delegate": run_openclaw_delegate_action,
        "goal": run_goal_action,
    }
    missing_action_handlers = set(ACTION_SPECS) - set(natural_action_handlers)
    if missing_action_handlers:
        missing = ", ".join(sorted(missing_action_handlers))
        raise RuntimeError(f"Missing Telegram natural action handlers: {missing}")

    async def handle_natural_intent(message: Message) -> bool:
        assert message.text is not None
        intent = await route_natural_intent(agent.provider, message.text)
        if not intent.should_handle:
            return False

        if not is_allowed_during_memory_job(intent.intent):
            if active := active_memory_job_message():
                await message.answer(active)
                return True

        handler = natural_action_handlers.get(intent.intent)
        if handler is None:
            return False
        await handler(message, intent.args)
        return True

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
        if active := active_memory_job_message():
            await message.answer(active)
            return
        query = (message.text or "").replace("/recall", "", 1).strip()
        await answer_recall(message, query)

    @dp.message(Command("context"))
    async def context(message: Message) -> None:
        if active := active_memory_job_message():
            await message.answer(active)
            return
        query = (message.text or "").replace("/context", "", 1).strip()
        await answer_context_preview(message, query)

    @dp.message(Command("memory_status"))
    async def memory_status(message: Message) -> None:
        await answer_memory_status(message)

    @dp.message(Command("core_memory"))
    async def core_memory(message: Message) -> None:
        await message.answer((await agent.render_core_memory())[:3900])

    @dp.message(Command("set_core_memory"))
    async def set_core_memory(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) != 3:
            await message.answer("Usage: /set_core_memory <block> <text>")
            return
        _command, label, value = parts
        await message.answer(await agent.set_core_memory(label, value))

    @dp.message(Command("memory_audit"))
    async def memory_audit(message: Message) -> None:
        audit = build_memory_audit(agent.memory, ingest_runs, source_items)
        await message.answer(render_memory_audit(audit)[:3900])

    @dp.message(Command("goal"))
    async def goal(message: Message) -> None:
        text = (message.text or "").replace("/goal", "", 1).strip()
        lowered = text.lower()
        if not text or lowered == "show":
            await message.answer((await agent.render_goal())[:3900])
            return
        if lowered == "clear":
            await message.answer(await agent.clear_goal())
            return
        if lowered == "status":
            today_context = chat_events.today_context(str(message.chat.id), limit=4, max_chars=700)
            await message.answer((await agent.goal_status(text, today_context=today_context))[:3900])
            return
        if lowered.startswith("set "):
            text = text[4:].strip()
        await message.answer(await agent.set_goal(text))

    @dp.message(Command("memory_jobs"))
    async def memory_jobs_status(message: Message) -> None:
        await message.answer(memory_jobs.render()[:3900])

    @dp.message(Command("cancel_memory_job"))
    async def cancel_memory_job(message: Message) -> None:
        if memory_jobs.cancel_current():
            await message.answer("Cancellation requested for the active memory job.")
        else:
            await message.answer("No active memory job to cancel.")

    @dp.message(Command("refresh_memory"))
    async def refresh_memory(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip().lower() not in {"all"}:
            await message.answer("Usage: /refresh_memory [all]")
            return

        async def runner() -> None:
            await run_full_refresh(message)

        await enqueue_memory_job(message, "refresh_memory", runner)

    async def run_full_refresh(message: Message) -> None:
        await message.answer("Refresh step 1/4: ingesting local memory sources.")
        await run_local_memory_ingest_job(message, limit=None)
        await message.answer("Refresh step 2/4: ingesting Obsidian changes.")
        await run_obsidian_ingest_job(message, limit=None, ingest_all=True)
        await message.answer("Refresh step 3/5: evolving Frakir Palace in Obsidian.")
        palace_dir = settings.obsidian_vault_path / "Frakir Palace"
        await build_palace(memory=agent.memory, provider=agent.provider, output_dir=palace_dir, ingest=False)
        await message.answer(f"Frakir Palace updated: {palace_dir}")
        if agent.core_memory is not None:
            await message.answer("Refresh step 4/5: syncing core memory from Frakir Palace.")
            result = await sync_core_memory_from_palace(
                core_memory=agent.core_memory,
                provider=agent.provider,
                palace_dir=palace_dir,
            )
            labels = ", ".join(result.updates) if result.updates else "none"
            await message.answer(f"Core memory sync complete. Updated blocks: {labels}.")
        else:
            await message.answer("Refresh step 4/5: core memory disabled; skipping Palace sync.")
        await message.answer("Refresh step 5/5: ingesting changed palace notes from Obsidian.")
        await run_obsidian_ingest_job(message, limit=None, ingest_all=True)

    @dp.message(Command("rebuild_memory"))
    async def rebuild_memory(message: Message) -> None:
        if (message.text or "").strip() != "/rebuild_memory confirm":
            await message.answer("Usage: /rebuild_memory confirm")
            return
        if not approvals.is_allowed("memory.reset"):
            await message.answer("memory.reset is not allowed by policy. Temporarily set it to allow first.")
            return

        async def runner() -> None:
            await message.answer("Resetting Cognee memory and import manifests before rebuild.")
            await agent.memory.reset()
            ingest_runs.clear_manifest()
            source_items.clear()
            await message.answer("Cognee reset complete. Rebuilding without raw .jsonl local memory sources.")
            await run_full_refresh(message)

        await enqueue_memory_job(message, "rebuild_memory", runner)

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
        await answer_skill_mode(message, parts[1])

    @dp.message(Command("reset_memory"))
    async def reset_memory(message: Message) -> None:
        if active := active_memory_job_message():
            await message.answer(active)
            return
        if (message.text or "").strip() != "/reset_memory confirm":
            await message.answer("Usage: /reset_memory confirm")
            return
        if not approvals.is_allowed("memory.reset"):
            await message.answer("memory.reset is not allowed by policy. Temporarily set it to allow first.")
            return
        await message.answer("Resetting Cognee memory and ingest manifest.")
        await agent.memory.reset()
        ingest_runs.clear_manifest()
        source_items.clear()
        await message.answer("Memory reset complete. Re-run /ingest_obsidian all.")

    @dp.message(Command("remember"))
    async def remember(message: Message) -> None:
        if active := active_memory_job_message():
            await message.answer(active)
            return
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

    @dp.message(Command("pkill"))
    async def pkill(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        allowed = ", ".join(sorted(PKILL_TARGETS))
        if len(parts) != 2:
            await message.answer(f"Usage: /pkill <{allowed}>")
            return
        target = parts[1].strip().lower()
        if target not in PKILL_TARGETS:
            await message.answer(f"Unknown pkill target: {target}\nAllowed: {allowed}")
            return
        if not approvals.is_allowed("process.pkill"):
            await message.answer("process.pkill is not allowed by policy.")
            return
        if target == "agent":
            await message.answer("Stopping Frakir agent process. Restart from terminal after it exits.")
        try:
            result = await run_pkill(target)
        except Exception as exc:
            await message.answer(f"pkill failed: {type(exc).__name__}: {exc}")
            return
        if target == "agent":
            return
        if result.killed:
            await message.answer(f"pkill {target}: stopped matching process.")
        elif result.not_found:
            await message.answer(f"pkill {target}: no matching process found.")
        else:
            details = f"\n{result.stderr}" if result.stderr else ""
            await message.answer(f"pkill {target}: exited {result.returncode}.{details}")

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
        await enqueue_memory_job(
            message,
            "ingest_obsidian",
            lambda: run_obsidian_ingest_job(message, limit=limit, ingest_all=ingest_all),
        )

    @dp.message(Command("ingest_status"))
    async def ingest_status(message: Message) -> None:
        run = ingest_runs.latest()
        if run is None:
            await message.answer("No ingest runs yet.")
            return
        await message.answer(render_ingest_status(run, ingest_runs, source_items))

    @dp.message(Command("ingest_source"))
    async def ingest_source(message: Message) -> None:
        if active := active_memory_job_message():
            await message.answer(active)
            return
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
        await enqueue_memory_job(
            message,
            f"ingest_source:{source}",
            lambda: run_chat_source_ingest_job(message, source, export_path, limit),
        )

    @dp.message(Command("ingest_memories"))
    async def ingest_memories(message: Message) -> None:
        parts = (message.text or "").split(maxsplit=1)
        limit = DEFAULT_INGEST_LIMIT
        if len(parts) == 2:
            arg = parts[1].strip().lower()
            if arg == "all":
                limit = None
            elif arg.isdigit():
                limit = int(arg)
            else:
                await message.answer("Usage: /ingest_memories [limit|all]")
                return
        await enqueue_memory_job(
            message,
            "ingest_memories",
            lambda: run_local_memory_ingest_job(message, limit=limit),
        )

    @dp.message(Command("ingest_summaries"))
    async def ingest_summaries(message: Message) -> None:
        if active := active_memory_job_message():
            await message.answer(active)
            return
        parts = (message.text or "").split(maxsplit=1)
        limit = DEFAULT_INGEST_LIMIT
        if len(parts) == 2:
            arg = parts[1].strip().lower()
            if arg == "all":
                limit = None
            elif arg.isdigit():
                limit = int(arg)
            else:
                await message.answer("Usage: /ingest_summaries [limit|all]")
                return
        await enqueue_memory_job(
            message,
            "ingest_summaries",
            lambda: run_summary_ingest_job(message, limit),
        )

    @dp.message(F.text)
    async def chat(message: Message) -> None:
        assert message.text is not None
        if await handle_natural_intent(message):
            return
        if active := active_memory_job_message():
            await message.answer(active)
            return
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


def _load_non_obsidian_summary_documents() -> list[LocalMemoryDocument]:
    docs = list(load_local_memory_documents())
    for source in ("chatgpt", "claude", "openclaw"):
        export_path = _source_path(source)
        if export_path is None:
            continue
        for chat_doc in load_chat_documents(source, export_path):
            docs.append(
                LocalMemoryDocument(
                    source=chat_doc.source,
                    item_id=chat_doc.item_id,
                    title=chat_doc.title,
                    text=chat_doc.text,
                )
            )
    return docs


def render_ingest_status(
    run: IngestRun,
    ingest_runs: IngestRunStore,
    source_items: SourceItemStore,
) -> str:
    lines = [
        f"Ingest #{run.id}: {run.status}",
        f"Source: {run.source}",
        f"Progress: {run.processed_files}/{run.total_files}",
    ]
    if run.source == "vault":
        lines.extend(
            [
                f"Completed files: {ingest_runs.completed_count()}",
                f"Failed files: {ingest_runs.failed_count()}",
                f"Processed files: {ingest_runs.terminal_count()}",
            ]
        )
    elif run.source in {"local_memories", "apfel_summaries"}:
        lines.extend(_local_memory_source_counts(source_items))
    else:
        lines.extend(
            [
                f"Imported items: {source_items.count(run.source)}",
                f"Completed items: {source_items.count(run.source, 'completed')}",
                f"Failed items: {source_items.count(run.source, 'failed')}",
            ]
        )
    lines.extend([f"Last update: {run.updated_at}", f"Last: {run.message or '-'}"])
    return "\n".join(lines)


def _local_memory_source_counts(source_items: SourceItemStore) -> list[str]:
    sources = [
        "openclaw_workspace",
        "openclaw_workspace_memory",
        "claude_projects",
        "codex_projects",
        "claude_project_memory",
        "openclaw_sessions",
        "claude_global",
    ]
    total = sum(source_items.count(source) for source in sources)
    completed = sum(source_items.count(source, "completed") for source in sources)
    failed = sum(source_items.count(source, "failed") for source in sources)
    return [
        f"Imported items: {total}",
        f"Completed items: {completed}",
        f"Failed items: {failed}",
    ]
