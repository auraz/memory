# Personal Memory Agent

Local-first Telegram personal assistant with long-term memory through Cognee, OpenAI or Anthropic LLM providers, a read-only Obsidian importer, and text-file approval gates.

## Current Shape

- Runs locally on a Mac.
- Uses Telegram as the control surface.
- Uses OpenAI or Anthropic via environment configuration.
- Maps `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` into Cognee's `LLM_API_KEY`.
- Recalls relevant long-term memory automatically before normal chat responses.
- Reads Obsidian notes from `OBSIDIAN_VAULT_PATH` and never writes back to the vault.
- Stores Cognee data under `data/cognee/` by default.
- Stores approval policy in `config/approvals.yaml`.
- Starts gated: memory recall and Obsidian reads are allowed, most actions require approval or are denied.

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
- `/approve <id>` runs a queued action.
- `/deny <id>` rejects a queued action.
- `/ingest_obsidian [limit|all]` imports the next uningested markdown notes from the configured vault. Defaults to 25 notes.
- `/ingest_source <chatgpt|claude|openclaw> [limit|all]` imports exported chat conversations from configured paths.
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

Supported ingest sources:

- Obsidian markdown vault via `OBSIDIAN_VAULT_PATH`
- ChatGPT exports via `CHATGPT_EXPORT_PATH`
- Claude exports via `CLAUDE_EXPORT_PATH`
- OpenClaw or generic chat exports via `OPENCLAW_EXPORT_PATH`

Chat exports can be JSON, JSONL, or Markdown. ChatGPT `conversations.json` and common Claude export JSON shapes are parsed into conversation transcripts before indexing.

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
```

Or from the CLI:

```bash
chat-export-ingest chatgpt /path/to/conversations.json --limit 25
```

## Policy

Policy lives in `config/approvals.yaml`.

Modes:

- `allow`: tool can run immediately.
- `require_approval`: tool must be staged for approval before running.
- `deny`: tool cannot run.

The MVP allows automatic recall:

```yaml
tools:
  memory.recall:
    mode: allow
```

This matches the intended direction: eventually more things can run without manual approval, but only when the policy gate explicitly allows them.

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
