# Frakir Memory Agent

Frakir is a local-first Telegram agent that turns personal knowledge into usable context: small Letta-style core memory blocks, Obsidian notes, Claude/Codex/OpenClaw project memories, chat exports, and same-day Telegram history.

It is built for a private Mac workflow first, with public, inspectable code: read-only importers, explicit local storage, configurable OpenAI/Anthropic models, OpenClaw delegation, and a policy file for deciding which actions run automatically.

## Current Shape

- Runs locally on a Mac.
- Uses Telegram as the control surface.
- Uses OpenAI or Anthropic via environment configuration.
- Maps `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` into Cognee's `LLM_API_KEY`.
- Uses small core memory blocks for stable always-visible context.
- Uses focused Cognee archive recall for normal chat responses.
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

For a one-shot terminal turn:

```bash
agent -- success business stories
agent --context -- success business stories
agent --set-goal "Make Frakir memory-first and use OpenClaw as the tool runtime."
agent --goal-status
```

To watch Frakir and Cognee logs for warnings/errors in another terminal:

```bash
memory-agent-watch-errors
```

For long jobs such as full-vault ingest, prefer `memory-agent` over `memory-agent-dev`.
The dev runner restarts on file changes and can interrupt an active Cognee pipeline.

## Telegram Chat

Normal chat is the primary interface. Frakir preloads core memory, same-day Telegram context, focused Cognee recall, and an answer skill before replying.
While Frakir is routing, recalling, calling the model, or delegating to OpenClaw, Telegram shows the bot as typing. Long background jobs still report progress as messages.

You can also use natural control phrases instead of slash commands:

```text
show core memory
memory status
show goal
set goal reuse OpenClaw as Frakir's tool runtime
goal status
recall emotions
context for what should I focus on now
use planner skill
skill auto
refresh memory
remember that I prefer short answers
ask OpenClaw to inspect the latest logs
search the internet for latest Letta docs
create a Google Sheet called Weekly Goals with columns Goal, Owner, Status
append these rows to spreadsheet <id>
```

Slash commands remain available for debug/admin work and explicit dangerous actions such as reset, rebuild, approvals, and process stopping.

Natural controls are backed by a typed action catalog in `app/bot/actions.py`. The LLM router chooses an action and arguments, Pydantic validates the arguments, and Telegram executes the matching action. The same catalog can export MCP-style or OpenAI-style tool schemas through `export_action_tool_schemas()`, which is the boundary to swap later into Pydantic AI tools or MCP tools without changing the Telegram UX.

When you reply to a Telegram message, Frakir includes that replied message as explicit context. This means short follow-ups like `search this`, `remember this`, or `what about this?` operate on the replied message instead of guessing from the current topic.

## Telegram Commands

- `/start` confirms the local agent is running.
- `/recall <topic>` recalls memory directly.
- `/context <message>` previews the long-term memory packet and skill that a normal answer would receive.
- `/memory_status` shows whether memory is using Cognee or volatile fallback.
- `/memory_audit` reports memory integrity counters and recent Cognee errors.
- `/goal [show|status|clear|set <text>|<text>]` manages the active goal stored in core memory.
- `/core_memory` shows the current Letta-style core memory blocks.
- `/set_core_memory <block> <text>` updates a core memory block.
- `/refresh_memory [all]` queues a background refresh inside the running bot: local memories, Obsidian, Frakir Palace, then changed palace notes.
- `/rebuild_memory confirm` resets Cognee and import manifests, then runs a full refresh. Use this after changing source filters, for example after excluding `.jsonl` transcripts.
- `/memory_jobs` shows the active and latest background memory job.
- `/cancel_memory_job` asks the active memory job to stop.
- `/skills` lists answer skills.
- `/skill <name|auto|off>` sets the current chat's answer skill.
- `/reset_memory confirm` clears Cognee's local `system`, `storage`, and `cache` data plus the ingest manifest when `memory.reset` is allowed.
- `/remember <text>` proposes or stores a memory in Frakir Palace first, then indexes that entry into Cognee.
- `/pending` shows queued gated actions.
- `/openclaw <task>` delegates a task to OpenClaw through `openclaw.agent_send`.
- Google Workspace actions are natural-language only for now: create/read/update/append Google Sheets through `gws.sheets.*`.
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
Each skill is a small workflow contract: answer instructions, memory scope, tool policy, output format, and a per-skill Cognee context budget. This keeps debugging/building/memory answers from inheriting broad archive context as accidental requirements.

```text
/skills
/skill auto
/skill research
/skill coach
/skill brainstorm
/skill planner
/skill journal
/skill debug
/skill build
/skill decision
/skill memory
/skill off
```

## Google Workspace Tools

Frakir has a Google Workspace tool layer, with Google Sheets as the first supported surface. It is deterministic tool execution, not browser automation:

- `gws.sheets.create`: create a spreadsheet, optionally with starter rows.
- `gws.sheets.read`: read a range such as `Sheet1!A1:D20`.
- `gws.sheets.update`: replace values in a range.
- `gws.sheets.append`: append rows to a worksheet.

Set up OAuth once on the local Mac:

```bash
mkdir -p config/google
# Save a Google Cloud OAuth desktop client secret here:
# config/google/client_secret.json
uv run --reinstall-package personal-memory-agent gws-auth
```

The auth command stores the local user token at `data/google/authorized_user.json`, which is ignored by git. The default scopes are:

```text
https://www.googleapis.com/auth/drive.file
https://www.googleapis.com/auth/spreadsheets
```

Natural examples:

```text
create a Google Sheet called Weekly Goals with columns Goal, Owner, Status
read Sheet1 A1:D20 from spreadsheet <id>
append rows to spreadsheet <id>: Project, Status / Frakir, Active
```

Policy defaults are conservative for writes:

```yaml
gws.sheets.read:
  mode: allow
gws.sheets.create:
  mode: require_approval
gws.sheets.update:
  mode: require_approval
gws.sheets.append:
  mode: require_approval
```

`/skill auto` uses the configured LLM to route the message to the best answer skill, with deterministic fallback if routing fails. For example, “what did I work on emotions?” routes to `research`, while “brainstorm options” routes to `brainstorm`.

Examples:

- `debug` keeps Cognee context very narrow and returns root cause, verification, fix, residual risk.
- `memory` focuses on ingest/recall quality and avoids bulk resets unless explicitly confirmed.
- `decision` uses durable preferences from core memory and returns options, tradeoffs, recommendation.

## Memory Sources

Normal chat messages include core memory first, then a small focused Cognee archive packet. `/recall <topic>` is a direct recall/debug command.
Normal chat messages also include a compact "today with this Telegram chat" context from the same chat, saved locally in SQLite.

## Core Memory

Core memory follows Letta's memory-block model: small persistent blocks stay in context, while Cognee remains the larger searchable archive. This avoids treating every archive hit as a requirement.

Default local blocks:

- `human`
- `persona`
- `active_projects`
- `active_goal`
- `preferences`
- `current_focus`

Use Telegram to inspect or edit them:

```text
/core_memory
/goal status
/set_core_memory current_focus Keep current answers focused; ignore stale archive requirements unless directly relevant.
```

Explicit remember requests are written into Frakir Palace first. Preference-like memories go to `preferences.md`; project/goal memories go to `active_projects.md`; unclear memories go to `inbox.md`. Frakir then indexes the same entry into Cognee with a `palace:remember:*` source.

Normal Telegram messages can update core memory automatically when they contain durable facts, preferences, project changes, or an explicit "remember" instruction. This is intentionally conservative: Frakir asks the model for a strict JSON patch against the small core blocks, ignores one-off task details, and never bulk-copies Cognee recall into Letta. Disable this with `CORE_MEMORY_AUTO_UPDATE=false`.

To build the initial core memory set from the Frakir Palace after a full import:

```bash
uv run --reinstall-package personal-memory-agent palace-build --output "../../1.Stable/ExpressionVault/Frakir Palace"
uv run --reinstall-package personal-memory-agent core-memory-sync --palace-dir "../../1.Stable/ExpressionVault/Frakir Palace"
```

Use `--dry-run` first to inspect the proposed block replacements without writing them.
`core-memory-seed` remains as a backward-compatible alias for the same Palace-to-core sync.

By default these blocks are stored in SQLite. To read/write blocks from a Letta server instead, install the optional client and configure an existing Letta agent:

```bash
uv sync --extra letta --extra dev
```

Start a local Letta server in Docker. The command reads `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from the current shell and passes whichever are set into the container:

```bash
uv run letta-docker-start
```

```text
LETTA_ENABLED=true
LETTA_BASE_URL=http://localhost:8283
LETTA_API_KEY=
LETTA_AGENT_ID=...
```

Frakir still keeps a local SQLite copy as fallback. Cognee remains the archive; Letta/core memory controls what is always visible.

## OpenClaw Delegation

`/openclaw <task>` runs a delegated OpenClaw agent turn. By default this uses:

```bash
openclaw agent --message "<task>" --session-id "frakir-telegram-<chat-id>" --timeout 600 --json --local
```

Configure it with `OPENCLAW_CLI_PATH`, `OPENCLAW_AGENT_ID`, `OPENCLAW_LOCAL`, and `OPENCLAW_TIMEOUT_SECONDS`.
The default approval policy is `openclaw.agent_send: allow`, so Frakir runs OpenClaw delegation immediately.

Explicit web/current-info requests are routed to OpenClaw with instructions to use web search or browser tools, answer in English unless the request uses another language, and cite links. Frakir's normal model prompt does not claim absolute lack of internet access; it states that web/current-info work can be delegated to OpenClaw.

Supported ingest sources:

- Obsidian markdown vault via `OBSIDIAN_VAULT_PATH`
- Curated local memories via `/ingest_memories`:
  - `OPENCLAW_WORKSPACE_PATH` root files: `IDENTITY.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `MEMORY.md`, `HEARTBEAT.md`
  - `OPENCLAW_WORKSPACE_PATH/memory/**/*.{md,qmd,txt,json}`
  - `CLAUDE_PROJECTS_PATH/**/*.{md,qmd,txt,json}`
  - `CODEX_PROJECTS_PATH/**/*.{md,qmd,txt,json}`
  - `CLAUDE_PROJECT_MEMORY_PATH/**/*.{md,qmd,txt,json}`
  - `OPENCLAW_SESSIONS_PATH/**/*.{md,qmd,txt,json}`
  - `CLAUDE_GLOBAL_PATH`
- ChatGPT exports via `CHATGPT_EXPORT_PATH`
- Claude exports via `CLAUDE_EXPORT_PATH`
- OpenClaw or generic chat exports via `OPENCLAW_EXPORT_PATH`

Chat exports can be JSON, JSONL, or Markdown. ChatGPT `conversations.json` and common Claude export JSON shapes are parsed into conversation transcripts before indexing.
Local memory imports are incremental: unchanged files are skipped by size/mtime metadata, new files are indexed fully, and changed daily/session-style sources index only added text against the previous sanitized snapshot.
Raw `.jsonl` files are excluded from local memory discovery because they are usually noisy session transcripts. Use curated Markdown, text, JSON summaries, or explicit chat export import instead.
Large `claude_projects` files are summarized with local Apple Intelligence through `apfel` before Cognee indexing. Telegram reports slow stages such as `summarizing with apfel 2/6` and `indexing chunk 1/3` during `/ingest_memories`. The manifest still stores the sanitized original text for future changed-file diffs. Configure with `APFEL_CLI_PATH`, `APFEL_SUMMARY_SOURCES`, `APFEL_SUMMARY_MIN_CHARS`, `APFEL_SUMMARY_CHUNK_CHARS`, `APFEL_SUMMARY_MAX_CHUNKS`, and `APFEL_SUMMARY_TIMEOUT_SECONDS`.
If Apfel rejects a chunk with an unsupported language, the importer translates that chunk to English with the configured LLM provider and retries Apfel. If Apfel still rejects the translated text, or if Apfel hits its context window, the configured LLM produces the compact memory summary directly so the batch can continue. Disable translation with `APFEL_TRANSLATE_UNSUPPORTED_LANGUAGE=false`, or disable the final LLM summary fallback with `APFEL_LLM_FALLBACK_ON_UNSUPPORTED_LANGUAGE=false`.

For daily background updates, prefer Telegram:

```text
/refresh_memory
/memory_jobs
```

The refresh runs inside the already-running bot process, so the bot owns Cognee/Kuzu while it updates memory. Avoid running `obsidian-ingest`, `local-memory-ingest`, or `palace-build` as separate CLIs at the same time as the Telegram agent; those separate processes can hit Cognee database locks.
`/refresh_memory` also syncs Frakir Palace into Letta/core memory before re-ingesting the changed Palace notes.
If already-indexed sources need to be removed from Cognee, use `/rebuild_memory confirm`; it clears Cognee and rebuilds from the currently allowed sources.

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

The plan step is local and cheap. `summarize` processes worthwhile candidates by default. It skips existing summaries and empty/tiny low-signal files. Raw `.jsonl` transcripts are not discovered by local memory import; use compact Markdown/text/JSON summaries instead. Use `--all-candidates` if you want to override the worthwhile filter.

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
