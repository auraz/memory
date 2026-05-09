# Frakir Memory Agent

Frakir is a local-first Telegram agent that turns personal knowledge into usable context: Obsidian notes, Claude/Codex/OpenClaw project memories, chat exports, and same-day Telegram history are indexed into durable Cognee memory and recalled before every answer.

It is built for a private Mac workflow first, with public, inspectable code: read-only importers, explicit local storage, configurable OpenAI/Anthropic models, OpenClaw delegation, and a policy file for deciding which actions run automatically.

## Current Shape

- Runs locally on a Mac.
- Uses Telegram as the control surface.
- Uses OpenAI or Anthropic via environment configuration.
- Maps `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` into Cognee's `LLM_API_KEY`.
- Recalls relevant long-term memory automatically before normal chat responses.
- Reads Obsidian notes from `OBSIDIAN_VAULT_PATH` and never writes back to the vault.
- Stores Cognee data under `data/cognee/` by default.
- Stores approval policy in `config/approvals.yaml`.
- Starts auto-approved by default, with explicitly dangerous actions such as raw shell and Obsidian writes denied.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Fill in `.env`:

```text
TELEGRAM_BOT_TOKEN_FRAKIR=...
LLM_PROVIDER=openai
OPENAI_API_KEY=...
```

For Anthropic:

```text
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=...
```

## Obsidian Vault

The configured default is:

```text
../../1.Stable/ExpressionVault
```

That resolves from this repo to:

```text
/Users/ok/Documents/02-areas/career/repos/1.Stable/ExpressionVault
```

If the vault moves, update `OBSIDIAN_VAULT_PATH` in `.env`.

The importer is read-only by construction: it only walks `*.md` files and opens them with read mode.

## Run

```bash
memory-agent
```

Or:

```bash
python -m app.main
```

For development autoreload:

```bash
memory-agent-dev
```

To watch Frakir and Cognee logs for warnings/errors in another terminal:

```bash
memory-agent-watch-errors
```

For long jobs such as full-vault ingest, prefer `memory-agent` over `memory-agent-dev`.
The dev runner restarts on file changes and can interrupt an active Cognee pipeline.

## Telegram Commands

- `/start` confirms the local agent is running.
- `/recall <topic>` recalls memory directly.
- `/context <message>` previews the long-term memory packet and skill that a normal answer would receive.
- `/memory_status` shows whether memory is using Cognee or volatile fallback.
- `/memory_audit` reports memory integrity counters and recent Cognee errors.
- `/skills` lists answer skills.
- `/skill <name|auto|off>` sets the current chat's answer skill.
- `/reset_memory confirm` clears Cognee's local `system`, `storage`, and `cache` data plus the ingest manifest when `memory.reset` is allowed.
- `/remember <text>` proposes or stores a memory depending on policy.
- `/pending` shows queued gated actions.
- `/openclaw <task>` delegates a task to OpenClaw through `openclaw.agent_send`.
- `/pkill <apfel|openclaw|agent>` stops allowlisted stuck local processes through `process.pkill`.
- `/approve <id>` runs a queued action.
- `/deny <id>` rejects a queued action.
- `/ingest_obsidian [limit|all]` imports the next uningested markdown notes from the configured vault. Defaults to 25 notes.
- `/ingest_source <chatgpt|claude|openclaw> [limit|all]` imports exported chat conversations from configured paths.
- `/ingest_memories [limit|all]` imports curated local memory files from OpenClaw, Claude, and Codex paths.
- `/ingest_status` shows the latest import status.
- `/approvals` shows the current policy file.
- `/set_approval <tool.name> <allow|require_approval|deny>` edits the policy.

If `/memory_status` reports `volatile in-memory fallback`, Cognee is not installed in the active environment and imported notes will be lost when the bot restarts. Cognee is a base dependency, so refresh the environment with:

```bash
uv run --reinstall-package personal-memory-agent memory-agent
```

## Answer Skills

Skills modify how the bot writes normal answers after automatic memory recall. They do not change the memory store.

```text
/skills
/skill auto
/skill research
/skill coach
/skill brainstorm
/skill planner
/skill journal
/skill off
```

`/skill auto` uses a deterministic router over the message text. For example, “what did I work on emotions?” routes to `research`, while “brainstorm options” routes to `brainstorm`.

## Memory Sources

Normal chat messages automatically recall from Cognee and pass the retrieved context into the LLM. `/recall <topic>` is a direct recall/debug command.
Normal chat messages also include a compact "today with this Telegram chat" context from the same chat, saved locally in SQLite.

## OpenClaw Delegation

`/openclaw <task>` runs a delegated OpenClaw agent turn. By default this uses:

```bash
openclaw agent --message "<task>" --session-id "frakir-telegram-<chat-id>" --timeout 600 --json --local
```

Configure it with `OPENCLAW_CLI_PATH`, `OPENCLAW_AGENT_ID`, `OPENCLAW_LOCAL`, and `OPENCLAW_TIMEOUT_SECONDS`.
The default approval policy is `openclaw.agent_send: allow`, so Frakir runs OpenClaw delegation immediately.

Supported ingest sources:

- Obsidian markdown vault via `OBSIDIAN_VAULT_PATH`
- Curated local memories via `/ingest_memories`:
  - `OPENCLAW_WORKSPACE_PATH` root files: `IDENTITY.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `MEMORY.md`, `HEARTBEAT.md`
  - `OPENCLAW_WORKSPACE_PATH/memory/**/*.{md,qmd,txt,json,jsonl}`
  - `CLAUDE_PROJECTS_PATH/**/*.{md,qmd,txt,json,jsonl}`
  - `CODEX_PROJECTS_PATH/**/*.{md,qmd,txt,json,jsonl}`
  - `CLAUDE_PROJECT_MEMORY_PATH/**/*.{md,qmd,txt,json,jsonl}`
  - `OPENCLAW_SESSIONS_PATH/**/*.{md,qmd,txt,json,jsonl}`
  - `CLAUDE_GLOBAL_PATH`
- ChatGPT exports via `CHATGPT_EXPORT_PATH`
- Claude exports via `CLAUDE_EXPORT_PATH`
- OpenClaw or generic chat exports via `OPENCLAW_EXPORT_PATH`

Chat exports can be JSON, JSONL, or Markdown. ChatGPT `conversations.json` and common Claude export JSON shapes are parsed into conversation transcripts before indexing.
Local memory imports are incremental: unchanged files are skipped by size/mtime metadata, new files are indexed fully, and changed daily/session-style sources index only added text against the previous sanitized snapshot.
Large `claude_projects` files are summarized with local Apple Intelligence through `apfel` before Cognee indexing. Telegram reports slow stages such as `summarizing with apfel 2/6` and `indexing chunk 1/3` during `/ingest_memories`. The manifest still stores the sanitized original text for future changed-file diffs. Configure with `APFEL_CLI_PATH`, `APFEL_SUMMARY_SOURCES`, `APFEL_SUMMARY_MIN_CHARS`, `APFEL_SUMMARY_CHUNK_CHARS`, `APFEL_SUMMARY_MAX_CHUNKS`, and `APFEL_SUMMARY_TIMEOUT_SECONDS`.
If Apfel rejects a chunk with an unsupported language, the importer translates that chunk to English with the configured LLM provider and retries Apfel. If Apfel still rejects the translated text, or if Apfel hits its context window, the configured LLM produces the compact memory summary directly so the batch can continue. Disable translation with `APFEL_TRANSLATE_UNSUPPORTED_LANGUAGE=false`, or disable the final LLM summary fallback with `APFEL_LLM_FALLBACK_ON_UNSUPPORTED_LANGUAGE=false`.

Set paths in the shell or `.env`:

```text
CHATGPT_EXPORT_PATH=/path/to/chatgpt/conversations.json
CLAUDE_EXPORT_PATH=/path/to/claude/export
OPENCLAW_EXPORT_PATH=/path/to/openclaw/export
```

Then ingest from Telegram:

```text
/ingest_source chatgpt 25
/ingest_source claude all
/ingest_source openclaw all
/ingest_memories all
```

Or from the CLI:

```bash
chat-export-ingest chatgpt /path/to/conversations.json --limit 25
local-memory-ingest --limit 25
```

For one-off non-Obsidian imports, generate local Apfel summaries first without touching Cognee:

```bash
apfel-summary-import plan
apfel-summary-import summarize --limit 25
apfel-summary-import summarize
```

The plan step is local and cheap. `summarize` processes worthwhile candidates by default. It skips existing summaries, empty/tiny low-signal files, Claude subagent transcripts, and raw Claude Code session `.jsonl` files when `sessions-index.json` already has a compact summary for that exact session. Use `--include-subagents` if you explicitly want to summarize raw Claude subagent implementation logs, or `--all-candidates` if you want to override the worthwhile filter.

Summaries are written to `data/apfel_summaries/` by default. After reviewing or generating them, ingest only those summary files into Cognee:

```bash
apfel-summary-import ingest --limit 25
apfel-summary-import ingest
```

After Obsidian and non-Obsidian summaries are imported, build draft memory palace rooms:

```bash
palace-build
palace-build --output "../../1.Stable/ExpressionVault/Frakir Palace"
palace-build --ingest
```

This writes `data/palace/about_me.md`, `cv.md`, `active_projects.md`, `preferences.md`, and `open_loops.md`. Files are marked draft because they are synthesized from recall and should be reviewed.
Palace files evolve incrementally: Frakir updates only the block between `<!-- FRAKIR:BEGIN generated -->` and `<!-- FRAKIR:END generated -->`, preserves manual notes outside that block, and uses the previous generated block as context for the next update. Generated rooms are written as normal Obsidian notes without `[M1]` citation markers. If you write palace files into the Obsidian vault, let regular Obsidian ingest pick them up instead of using `--ingest`, which avoids duplicate indexing.

## Policy

Policy lives in `config/approvals.yaml`.

Modes:

- `allow`: tool can run immediately.
- `require_approval`: tool must be staged for approval before running.
- `deny`: tool cannot run.

The default policy auto-approves tools:

```yaml
default: allow
tools:
  shell.run:
    mode: deny
  obsidian.write:
    mode: deny
```

Use explicit `deny` entries for actions that should never run, and `require_approval` for anything you want to temporarily gate.

## Large Vault Ingest

Cognee uses LanceDB locally. Large all-at-once imports can hit macOS file descriptor limits with `Too many open files`. Use repeated small batches:

```text
/ingest_obsidian
/ingest_obsidian 50
```

Each batch skips files already marked completed, so repeat the command until `/ingest_status` shows the completed count near the vault total.

To process the whole pending vault, use:

```text
/ingest_obsidian all
```

This still runs internally in batches of 25; it does not send the whole vault to Cognee as one batch.

The importer sanitizes markdown before indexing. Extremely long unbroken lines, usually base64 or embedded binary blobs, are removed because Cognee's chunker cannot split them safely.

Excalidraw notes are kept, but drawing payloads are stripped. Human-readable `Text Elements` remain indexable.

Failed files are marked failed and skipped on later batches, so one bad note does not stop the whole ingest. If you fix a source file, its file size/mtime changes and it becomes eligible for ingest again.

## Development

Run tests:

```bash
uv run --extra dev python -m pytest
```

Useful commands:

```bash
uv run --reinstall-package personal-memory-agent memory-agent
uv run --reinstall-package personal-memory-agent memory-agent-dev
uv run --reinstall-package personal-memory-agent memory-agent-watch-errors
uv run --reinstall-package personal-memory-agent memory-audit
```
