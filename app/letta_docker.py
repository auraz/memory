import os
import subprocess
from pathlib import Path


DEFAULT_IMAGE = "letta/letta:latest"
DEFAULT_CONTAINER = "frakir-letta"
DEFAULT_PORT = "8283"


def main() -> None:
    image = os.environ.get("LETTA_DOCKER_IMAGE", DEFAULT_IMAGE)
    container = os.environ.get("LETTA_DOCKER_CONTAINER", DEFAULT_CONTAINER)
    port = os.environ.get("LETTA_PORT", DEFAULT_PORT)
    persist_dir = Path(os.environ.get("LETTA_PERSIST_DIR", "~/.letta/.persist/pgdata")).expanduser()
    persist_dir.mkdir(parents=True, exist_ok=True)

    env_args: list[str] = []
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        value = os.environ.get(name)
        if value:
            env_args.extend(["-e", f"{name}={value}"])
    if not env_args:
        raise SystemExit("Set OPENAI_API_KEY or ANTHROPIC_API_KEY before starting Letta.")

    command = [
        "docker",
        "run",
        "--name",
        container,
        "--rm",
        "-v",
        f"{persist_dir}:/var/lib/postgresql/data",
        "-p",
        f"{port}:8283",
        *env_args,
        image,
    ]
    print(f"Starting Letta Docker container `{container}` on http://localhost:{port}", flush=True)
    print(f"Persistent data: {persist_dir}", flush=True)
    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
