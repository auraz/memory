import os
import inspect
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoryItem:
    text: str
    source: str | None = None


class CogneeMemory:
    """Thin adapter around Cognee with graceful fallback when Cognee is not installed."""

    def __init__(self, max_items: int = 8):
        self.max_items = max_items
        self._configure_storage()
        try:
            import cognee  # type: ignore
        except ImportError:
            cognee = None
        self._cognee = cognee
        self._fallback: list[MemoryItem] = []

    @property
    def backend_name(self) -> str:
        if self._cognee is None:
            return "volatile in-memory fallback"
        return "cognee"

    @property
    def is_durable(self) -> bool:
        return self._cognee is not None

    @property
    def storage_path(self) -> str:
        return os.environ.get("SYSTEM_ROOT_DIRECTORY", "unknown")

    async def remember(self, text: str, source: str | None = None) -> None:
        if self._cognee is None:
            self._fallback.append(MemoryItem(text=text, source=source))
            return
        await self._maybe_await(self._cognee.add(text))
        # Cognee APIs vary by version; keep processing explicit but tolerant.
        if hasattr(self._cognee, "cognify"):
            await self._maybe_await(self._cognee.cognify())

    async def recall(self, query: str) -> list[MemoryItem]:
        if self._cognee is None:
            lowered = query.lower()
            matches = [item for item in self._fallback if lowered in item.text.lower()]
            return matches[: self.max_items]

        if hasattr(self._cognee, "recall"):
            result = await self._maybe_await(self._cognee.recall(query, top_k=self.max_items))
        elif hasattr(self._cognee, "search"):
            result = await self._maybe_await(self._cognee.search(query, top_k=self.max_items))
        else:
            result = []
        return self._normalize(result)[: self.max_items]

    async def safe_recall(self, query: str) -> tuple[list[MemoryItem], str | None]:
        try:
            return await self.recall(query), None
        except Exception as exc:
            logging.exception("Memory recall failed")
            return [], f"{type(exc).__name__}: {exc}"

    def _normalize(self, result: object) -> list[MemoryItem]:
        if result is None:
            return []
        if isinstance(result, str):
            return [MemoryItem(text=result)]
        if isinstance(result, list):
            return [self._normalize_one(item) for item in result]
        return [self._normalize_one(result)]

    async def reset(self) -> None:
        if self._cognee is None:
            self._fallback.clear()
            return
        api_error: Exception | None = None
        if self._has_local_cognee_database() and hasattr(self._cognee, "forget"):
            try:
                await self._maybe_await(self._cognee.forget(everything=True))
            except Exception as exc:
                api_error = exc
        if self._has_local_cognee_database() and hasattr(self._cognee, "prune"):
            try:
                await self._maybe_await(self._cognee.prune.prune_data())
                await self._maybe_await(self._cognee.prune.prune_system(metadata=True))
            except Exception as exc:
                api_error = api_error or exc
        self._reset_storage_directories()
        if api_error is not None:
            logging.warning(
                "Cognee API reset failed; local storage was cleared",
                exc_info=(type(api_error), api_error, api_error.__traceback__),
            )

    def _normalize_one(self, item: object) -> MemoryItem:
        if isinstance(item, MemoryItem):
            return item
        if isinstance(item, dict):
            text = self._extract_text(item)
            source = self._extract_source(item)
            return MemoryItem(text=str(text), source=str(source) if source else None)
        return MemoryItem(text=str(item))

    def _extract_text(self, item: dict) -> str:
        search_result = item.get("search_result")
        if isinstance(search_result, list):
            return "\n".join(str(entry) for entry in search_result)
        if search_result:
            return str(search_result)
        return str(item.get("text") or item.get("content") or item.get("chunk") or item)

    def _extract_source(self, item: dict) -> str | None:
        direct = item.get("source") or item.get("path")
        if direct:
            return str(direct)
        dataset = item.get("dataset_name")
        source = item.get("_source")
        if dataset and source:
            return f"{source}:{dataset}"
        if dataset:
            return str(dataset)
        if source:
            return str(source)
        return None

    async def _maybe_await(self, value: object) -> object:
        if inspect.isawaitable(value):
            return await value
        return value

    def _configure_storage(self) -> None:
        self._configure_llm_env()
        defaults = {
            "SYSTEM_ROOT_DIRECTORY": "data/cognee/system",
            "DATA_ROOT_DIRECTORY": "data/cognee/storage",
            "CACHE_ROOT_DIRECTORY": "data/cognee/cache",
            "COGNEE_LOGS_DIR": "data/cognee/logs",
        }
        for key, value in defaults.items():
            path = Path(os.environ.get(key, value)).expanduser()
            os.environ[key] = str(path.resolve())
            path.mkdir(parents=True, exist_ok=True)

    def _reset_storage_directories(self) -> None:
        for key in ("SYSTEM_ROOT_DIRECTORY", "DATA_ROOT_DIRECTORY", "CACHE_ROOT_DIRECTORY"):
            path = Path(os.environ[key]).expanduser().resolve()
            if not self._is_safe_cognee_path(path):
                raise RuntimeError(f"Refusing to delete unsafe Cognee path: {path}")
            shutil.rmtree(path, ignore_errors=True)
            path.mkdir(parents=True, exist_ok=True)

    def _has_local_cognee_database(self) -> bool:
        system_root = Path(os.environ["SYSTEM_ROOT_DIRECTORY"]).expanduser().resolve()
        databases_dir = system_root / "databases"
        return databases_dir.exists() and any(databases_dir.iterdir())

    def _is_safe_cognee_path(self, path: Path) -> bool:
        if path in {Path("/"), Path.home(), Path.cwd().resolve()}:
            return False
        return any("cognee" in part.lower() for part in path.parts)

    def _configure_llm_env(self) -> None:
        app_provider = os.environ.get("LLM_PROVIDER", "openai").lower()

        if not os.environ.get("LLM_API_KEY"):
            if app_provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
                os.environ["LLM_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
            elif os.environ.get("OPENAI_API_KEY"):
                os.environ["LLM_API_KEY"] = os.environ["OPENAI_API_KEY"]

        if not os.environ.get("LLM_PROVIDER"):
            os.environ["LLM_PROVIDER"] = app_provider

        if not os.environ.get("LLM_MODEL"):
            if app_provider == "anthropic":
                model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
                os.environ["LLM_MODEL"] = f"anthropic/{model}"
            else:
                model = os.environ.get("OPENAI_MODEL", "gpt-5.5")
                os.environ["LLM_MODEL"] = f"openai/{model}"

        # Cognee defaults to OpenAI embeddings, so bridge the app's OpenAI key there too.
        if not os.environ.get("EMBEDDING_API_KEY") and os.environ.get("OPENAI_API_KEY"):
            os.environ["EMBEDDING_API_KEY"] = os.environ["OPENAI_API_KEY"]
