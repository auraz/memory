# Frakir Adds Memory-First Telegram Agent Workflow with OpenClaw and Google Workspace Tools

**Kyiv, Ukraine - May 11, 2026** - Frakir, a local-first personal memory agent, now combines durable personal memory, Telegram-first interaction, OpenClaw delegation, and Google Workspace actions in one workflow. The update moves Frakir beyond command-driven recall toward a conversational assistant that can understand natural follow-ups, maintain compact core memory, and execute structured external-tool work when needed.

Frakir now uses a layered memory design: Letta-style core memory for stable always-visible context, Cognee for searchable long-term archive recall, and an Obsidian-based Frakir Palace for human-readable curated memory. Explicit `remember` requests are written to Frakir Palace first, then indexed into Cognee, so durable memory remains inspectable and editable before being compacted into core memory.

Telegram is now the primary user interface. Frakir supports natural control phrases such as `show goal`, `remember that I prefer short answers`, `refresh memory`, and `search the internet for latest Letta docs`, while preserving slash commands for debug and administrative work. When users reply to a Telegram message with short follow-ups like `search this` or `remember this`, Frakir includes the replied message as explicit context, reducing ambiguity.

OpenClaw integration now acts as the execution layer. Frakir owns memory and context decisions, while OpenClaw handles external tool work such as web search, browser tasks, local inspection, and delegated agent execution. Web/current-info requests are sent to OpenClaw with explicit instructions to use web or browser tools, keep answers concise, and cite sources with links.

Google Workspace support starts with Sheets. Frakir can create spreadsheets, read ranges, update values, and append rows through deterministic `gws.sheets.*` actions. OAuth credentials stay local, and write operations are gated through the same approval policy used for other tools.

The release also adds a Telegram typing indicator during active work, making long LLM calls, recall, and OpenClaw delegation visible in chat. Background memory jobs continue to report progress through Telegram messages.

## Highlights

- Natural-language Telegram actions backed by typed Pydantic action schemas.
- Reply-aware context for Telegram follow-ups like `search this`.
- Letta-style core memory with Palace-to-core sync.
- Frakir Palace as the human-readable source for explicit remembered facts.
- OpenClaw delegation for web/current-info and local tool tasks.
- Google Sheets create/read/update/append through a Google Workspace tool layer.
- Telegram typing indicator while Frakir is working.
- One-shot CLI via `agent -- <message>` for terminal testing.

## Availability

Frakir is designed for private local Mac workflows. It runs as a Telegram bot backed by local SQLite state, Cognee storage, optional Letta server integration, and OpenClaw delegation.

## Example

```text
User replies to a prior Telegram message:
search this

Frakir:
- includes the replied message as search context
- routes the request to OpenClaw
- asks OpenClaw to use web/browser tools
- returns a concise sourced answer
```

## Project Positioning

Frakir is not trying to replace OpenClaw, Cognee, Letta, or Obsidian. It coordinates them:

- **Frakir** owns memory policy, context assembly, Telegram UX, and user-facing answers.
- **Cognee** stores searchable long-term archive memory.
- **Letta/core memory** stores compact always-visible context.
- **Frakir Palace in Obsidian** stores curated human-readable memory.
- **OpenClaw** provides tool execution, browser/search work, and delegated agent tasks.
- **Google Workspace tools** provide structured document and spreadsheet operations where deterministic APIs are better than browser automation.
