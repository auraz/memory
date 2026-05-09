import asyncio

import pytest

import app.tools.processes as processes


class FakeProcess:
    def __init__(self, returncode: int = 0, stderr: bytes = b""):
        self.returncode = returncode
        self._stderr = stderr

    async def communicate(self):
        return b"", self._stderr


def test_run_pkill_uses_allowlisted_pattern(monkeypatch):
    calls = []

    async def fake_exec(*args, **_kwargs):
        calls.append(args)
        return FakeProcess(returncode=0)

    monkeypatch.setattr(processes.asyncio, "create_subprocess_exec", fake_exec)

    result = asyncio.run(processes.run_pkill("apfel"))

    assert result.killed
    assert result.pattern == "apfel"
    assert calls == [("pkill", "-f", "apfel")]


def test_run_pkill_rejects_unknown_target():
    with pytest.raises(ValueError, match="Unknown pkill target"):
        asyncio.run(processes.run_pkill("python"))
