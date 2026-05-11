import subprocess

import pytest

import app.letta_docker as letta_docker


def test_letta_docker_start_builds_command(monkeypatch, tmp_path):
    calls = []

    def fake_call(command):
        calls.append(command)
        return 0

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("LETTA_PERSIST_DIR", str(tmp_path / "pgdata"))
    monkeypatch.setattr(subprocess, "call", fake_call)

    with pytest.raises(SystemExit) as exc:
        letta_docker.main()

    assert exc.value.code == 0
    command = calls[0]
    assert command[:2] == ["docker", "run"]
    assert "-e" in command
    assert "OPENAI_API_KEY=test-openai" in command
    assert "ANTHROPIC_API_KEY=test-anthropic" in command
    assert "letta/letta:latest" in command


def test_letta_docker_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(SystemExit) as exc:
        letta_docker.main()

    assert "Set OPENAI_API_KEY" in str(exc.value)
