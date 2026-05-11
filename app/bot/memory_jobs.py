import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone


JobRunner = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class MemoryJobSnapshot:
    id: int
    name: str
    status: str
    message: str
    started_at: str
    updated_at: str


class MemoryJobQueue:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._next_id = 1
        self._current_task: asyncio.Task[None] | None = None
        self._current: MemoryJobSnapshot | None = None
        self._latest: MemoryJobSnapshot | None = None

    async def start(self, name: str, runner: JobRunner) -> MemoryJobSnapshot | None:
        async with self._lock:
            if self.is_running:
                return None
            snapshot = MemoryJobSnapshot(
                id=self._next_id,
                name=name,
                status="running",
                message="started",
                started_at=_now(),
                updated_at=_now(),
            )
            self._next_id += 1
            self._current = snapshot
            self._latest = snapshot
            self._current_task = asyncio.create_task(self._run(snapshot, runner))
            self._current_task.add_done_callback(self._finalize_task)
            return snapshot

    @property
    def is_running(self) -> bool:
        return self._current_task is not None and not self._current_task.done()

    def active_snapshot(self) -> MemoryJobSnapshot | None:
        return self._current if self.is_running else None

    def latest_snapshot(self) -> MemoryJobSnapshot | None:
        return self._latest

    def cancel_current(self) -> bool:
        if not self.is_running or self._current_task is None:
            return False
        self._current_task.cancel()
        self._set_status("cancelling", "cancellation requested")
        return True

    def render(self) -> str:
        active = self.active_snapshot()
        latest = self.latest_snapshot()
        if active is None and latest is None:
            return "No memory jobs yet."
        lines: list[str] = []
        if active is not None:
            lines.extend(
                [
                    "Active memory job",
                    f"#{active.id} {active.name}: {active.status}",
                    f"Message: {active.message}",
                    f"Updated: {active.updated_at}",
                ]
            )
        else:
            lines.append("No active memory job.")
        if latest is not None and latest != active:
            lines.extend(
                [
                    "",
                    "Latest memory job",
                    f"#{latest.id} {latest.name}: {latest.status}",
                    f"Message: {latest.message}",
                    f"Updated: {latest.updated_at}",
                ]
            )
        return "\n".join(lines)

    async def _run(self, snapshot: MemoryJobSnapshot, runner: JobRunner) -> None:
        try:
            await runner()
        except asyncio.CancelledError:
            self._set_status("cancelled", "cancelled")
            raise
        except Exception as exc:
            self._set_status("failed", f"{type(exc).__name__}: {exc}")
        else:
            self._set_status("completed", "completed")

    def _set_status(self, status: str, message: str) -> None:
        snapshot = self._current
        if snapshot is None:
            return
        updated = MemoryJobSnapshot(
            id=snapshot.id,
            name=snapshot.name,
            status=status,
            message=message,
            started_at=snapshot.started_at,
            updated_at=_now(),
        )
        self._current = updated
        self._latest = updated

    def _finalize_task(self, task: asyncio.Task[None]) -> None:
        if task.cancelled() and self._latest is not None and self._latest.status == "cancelling":
            self._set_status("cancelled", "cancelled")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
