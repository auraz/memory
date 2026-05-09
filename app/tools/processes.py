import asyncio
from dataclasses import dataclass


PKILL_TARGETS = {
    "apfel": "apfel",
    "openclaw": "openclaw",
    "agent": r"memory-agent|app\.main|app\.dev",
}


@dataclass(frozen=True)
class PkillResult:
    target: str
    pattern: str
    returncode: int
    stderr: str

    @property
    def killed(self) -> bool:
        return self.returncode == 0

    @property
    def not_found(self) -> bool:
        return self.returncode == 1


async def run_pkill(target: str) -> PkillResult:
    normalized = target.strip().lower()
    pattern = PKILL_TARGETS.get(normalized)
    if pattern is None:
        allowed = ", ".join(sorted(PKILL_TARGETS))
        raise ValueError(f"Unknown pkill target: {target}. Allowed targets: {allowed}")

    process = await asyncio.create_subprocess_exec(
        "pkill",
        "-f",
        pattern,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await process.communicate()
    return PkillResult(
        target=normalized,
        pattern=pattern,
        returncode=process.returncode,
        stderr=stderr.decode("utf-8", errors="replace").strip(),
    )
