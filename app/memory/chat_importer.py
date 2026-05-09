import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.memory.cognee_store import CogneeMemory
from app.runtime_limits import raise_file_descriptor_limit
from app.settings import settings


@dataclass(frozen=True)
class ChatDocument:
    source: str
    item_id: str
    title: str
    text: str

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def load_chat_documents(source: str, export_path: Path) -> list[ChatDocument]:
    source = source.lower()
    if source not in {"chatgpt", "claude", "openclaw"}:
        raise ValueError("source must be one of: chatgpt, claude, openclaw")
    paths = _iter_export_files(export_path)
    docs: list[ChatDocument] = []
    for path in paths:
        if path.suffix.lower() == ".md":
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                docs.append(ChatDocument(source, str(path.resolve()), path.stem, text))
            continue
        if path.suffix.lower() == ".jsonl":
            docs.extend(_load_jsonl(source, path))
            continue
        if path.suffix.lower() == ".json":
            docs.extend(_load_json(source, path))
    return docs


def _iter_export_files(export_path: Path) -> list[Path]:
    path = export_path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Export path does not exist: {path}")
    if path.is_file():
        return [path]
    return sorted(
        child for child in path.rglob("*") if child.is_file() and child.suffix.lower() in {".json", ".jsonl", ".md"}
    )


def _load_json(source: str, path: Path) -> list[ChatDocument]:
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if source == "chatgpt":
        return _parse_chatgpt(data, path)
    if source == "claude":
        return _parse_claude(data, path)
    return _parse_generic_json(source, data, path)


def _load_jsonl(source: str, path: Path) -> list[ChatDocument]:
    docs: list[ChatDocument] = []
    for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        data = json.loads(line)
        text = _generic_transcript(data)
        if text:
            docs.append(ChatDocument(source, f"{path.resolve()}#{index}", _title(data, path.stem), text))
    return docs


def _parse_chatgpt(data: Any, path: Path) -> list[ChatDocument]:
    conversations = data if isinstance(data, list) else data.get("conversations", [])
    docs: list[ChatDocument] = []
    for index, conversation in enumerate(conversations):
        if not isinstance(conversation, dict):
            continue
        title = _title(conversation, f"chatgpt-{index}")
        mapping = conversation.get("mapping")
        if isinstance(mapping, dict):
            messages = []
            for node in mapping.values():
                message = node.get("message") if isinstance(node, dict) else None
                if isinstance(message, dict):
                    messages.append(message)
            messages.sort(key=lambda msg: msg.get("create_time") or 0)
            transcript = _messages_to_text(messages)
        else:
            transcript = _generic_transcript(conversation)
        if transcript:
            docs.append(ChatDocument("chatgpt", str(conversation.get("id") or f"{path.resolve()}#{index}"), title, transcript))
    return docs


def _parse_claude(data: Any, path: Path) -> list[ChatDocument]:
    conversations = data if isinstance(data, list) else data.get("conversations", [data])
    docs: list[ChatDocument] = []
    for index, conversation in enumerate(conversations):
        if not isinstance(conversation, dict):
            continue
        title = _title(conversation, f"claude-{index}")
        messages = conversation.get("chat_messages") or conversation.get("messages")
        transcript = _messages_to_text(messages) if isinstance(messages, list) else _generic_transcript(conversation)
        if transcript:
            docs.append(ChatDocument("claude", str(conversation.get("uuid") or conversation.get("id") or f"{path.resolve()}#{index}"), title, transcript))
    return docs


def _parse_generic_json(source: str, data: Any, path: Path) -> list[ChatDocument]:
    items = data if isinstance(data, list) else data.get("conversations", data.get("chats", [data])) if isinstance(data, dict) else []
    docs: list[ChatDocument] = []
    for index, item in enumerate(items):
        text = _generic_transcript(item)
        if text:
            docs.append(ChatDocument(source, str(_id(item) or f"{path.resolve()}#{index}"), _title(item, f"{source}-{index}"), text))
    return docs


def _messages_to_text(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = _role(message)
        text = _message_text(message)
        if text:
            lines.append(f"{role}: {text}")
    return "\n\n".join(lines)


def _generic_transcript(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        if all(isinstance(item, dict) for item in value):
            return _messages_to_text(value)
        return "\n\n".join(_generic_transcript(item) for item in value)
    if not isinstance(value, dict):
        return ""
    messages = value.get("messages") or value.get("chat_messages") or value.get("turns")
    if isinstance(messages, list):
        return _messages_to_text(messages)
    text = value.get("text") or value.get("content") or value.get("body")
    return str(text) if text else ""


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, dict):
        parts = content.get("parts")
        if isinstance(parts, list):
            return "\n".join(str(part) for part in parts if part)
        if "text" in content:
            return str(content["text"])
    if isinstance(content, list):
        return "\n".join(_generic_transcript(part) for part in content if part)
    if content:
        return str(content)
    return str(message.get("text") or message.get("body") or "")


def _role(message: dict[str, Any]) -> str:
    author = message.get("author")
    if isinstance(author, dict) and author.get("role"):
        return str(author["role"])
    return str(message.get("role") or message.get("sender") or "unknown")


def _title(value: Any, default: str) -> str:
    return str(value.get("title") or value.get("name") or default) if isinstance(value, dict) else default


def _id(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("id") or value.get("uuid") or value.get("conversation_id")
    return None


async def ingest_chat_documents(
    documents: list[ChatDocument],
    memory: CogneeMemory,
    limit: int | None = None,
) -> tuple[int, int]:
    ingested = 0
    failed = 0
    selected = documents if limit is None else documents[:limit]
    for document in selected:
        try:
            payload = f"Source: {document.source}:{document.title}\nConversation id: {document.item_id}\n\n{document.text}"
            await memory.remember(payload, source=f"{document.source}:{document.item_id}")
            ingested += 1
        except Exception:
            failed += 1
    return ingested, failed


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="Import chat exports into Cognee.")
    parser.add_argument("source", choices=["chatgpt", "claude", "openclaw"])
    parser.add_argument("path", type=Path)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    soft_limit, hard_limit = raise_file_descriptor_limit()
    print(f"Open file limit: soft={soft_limit} hard={hard_limit}", flush=True)
    memory = CogneeMemory(max_items=settings.max_context_items)
    docs = load_chat_documents(args.source, args.path)
    ingested, failed = await ingest_chat_documents(docs, memory, args.limit)
    print(f"Ingested {ingested} {args.source} conversations. Failed: {failed}.")


def main() -> None:
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
