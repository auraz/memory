import os

import pytest

import app.letta_docker as letta_docker


def test_letta_docker_requires_api_key():
    original_openai = os.environ.pop("OPENAI_API_KEY", None)
    original_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        with pytest.raises(SystemExit) as exc:
            letta_docker.main()
    finally:
        if original_openai is not None:
            os.environ["OPENAI_API_KEY"] = original_openai
        if original_anthropic is not None:
            os.environ["ANTHROPIC_API_KEY"] = original_anthropic

    assert "Set OPENAI_API_KEY" in str(exc.value)
