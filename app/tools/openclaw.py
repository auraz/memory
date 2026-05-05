import asyncio
import json
from dataclasses import dataclass


MAX_OPENCLAW_OUTPUT_CHARS = 3500


@dataclass(frozen=True)
class OpenClawResult:
    text: str
    stdout: str
    stderr: str
    returncode: int


async def run_openclaw_agent(
    message: str,
    session_id: str,
    cli_path: str = "openclaw",
    agent_id: str | None = None,
    local: bool = True,
    timeout_seconds: int = 600,
) -> OpenClawResult:
    command = [
        cli_path,
        "agent",
        "--message",
        message,
        "--session-id",
        session_id,
        "--timeout",
        str(timeout_seconds),
        "--json",
    ]
    if agent_id:
        command.extend(["--agent", agent_id])
    if local:
        command.append("--local")

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"OpenClaw CLI not found: {cli_path}") from exc

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds + 5,
        )
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise RuntimeError(f"OpenClaw timed out after {timeout_seconds} seconds") from exc

    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
    returncode = int(process.returncode or 0)
    if returncode != 0:
        detail = _compact(stderr or stdout or "no output", MAX_OPENCLAW_OUTPUT_CHARS)
        raise RuntimeError(f"OpenClaw exited with code {returncode}: {detail}")

    text = _extract_text(stdout) or stdout or stderr or "OpenClaw completed without output."
    return OpenClawResult(
        text=_compact(text, MAX_OPENCLAW_OUTPUT_CHARS),
        stdout=stdout,
        stderr=stderr,
        returncode=returncode,
    )


def _extract_text(stdout: str) -> str:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout
    extracted = _find_text(parsed)
    return extracted if extracted is not None else json.dumps(parsed, ensure_ascii=False)


def _find_text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "message", "reply", "output", "result"):
            item = value.get(key)
            found = _find_text(item)
            if found:
                return found
        for item in value.values():
            found = _find_text(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_text(item)
            if found:
                return found
    return None


def _compact(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."
