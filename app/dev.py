import fnmatch
import subprocess
import sys
import time
from pathlib import Path


WATCH_ROOTS = [Path("app"), Path("config"), Path(".env"), Path("pyproject.toml")]
WATCH_PATTERNS = ["*.py", "*.yaml", "*.yml", ".env", "pyproject.toml"]
LOG_PATH = Path("data/logs/frakir-dev.log")


def iter_watched_files() -> list[Path]:
    files: list[Path] = []
    for root in WATCH_ROOTS:
        if not root.exists():
            continue
        if root.is_file():
            files.append(root)
            continue
        for path in root.rglob("*"):
            if path.is_file() and any(fnmatch.fnmatch(path.name, pattern) for pattern in WATCH_PATTERNS):
                files.append(path)
    return sorted(files)


def snapshot() -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in iter_watched_files()}


def terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def start() -> subprocess.Popen[bytes]:
    print("Starting Frakir bot with autoreload. Press Ctrl+C to stop.", flush=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log = LOG_PATH.open("ab", buffering=0)
    log.write(b"\n--- Frakir dev process start ---\n")
    return subprocess.Popen([sys.executable, "-m", "app.main"], stdout=log, stderr=log)


def main() -> None:
    previous = snapshot()
    process = start()
    try:
        while True:
            time.sleep(1)
            current = snapshot()
            changed = current != previous
            exited = process.poll() is not None
            if changed:
                previous = current
                print("Change detected. Restarting Frakir bot.", flush=True)
                terminate(process)
                process = start()
            elif exited:
                print(
                    f"Frakir bot exited with code {process.returncode}. "
                    "Waiting for a file change before restart.",
                    flush=True,
                )
                while True:
                    time.sleep(1)
                    current = snapshot()
                    if current != previous:
                        previous = current
                        process = start()
                        break
    except KeyboardInterrupt:
        terminate(process)


if __name__ == "__main__":
    main()
