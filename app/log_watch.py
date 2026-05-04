import argparse
import re
import time
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PATHS = [Path("data/logs/frakir-dev.log"), Path("data/cognee/logs")]
ERROR_RE = re.compile(
    r"(error|exception|traceback|failed|failure|runtimeerror|warning|too many open files|llmapikeynotset)",
    re.IGNORECASE,
)


@dataclass
class WatchedFile:
    path: Path
    position: int = 0


def latest_log_file(directory: Path) -> Path | None:
    if not directory.exists():
        return None
    files = [path for path in directory.iterdir() if path.is_file()]
    return max(files, key=lambda path: path.stat().st_mtime_ns) if files else None


def resolve_paths(paths: list[Path]) -> list[Path]:
    resolved: list[Path] = []
    for path in paths:
        if path.is_dir():
            latest = latest_log_file(path)
            if latest is not None:
                resolved.append(latest)
        elif path.exists():
            resolved.append(path)
    return resolved


def read_new_lines(watched: WatchedFile) -> list[str]:
    if not watched.path.exists():
        return []
    size = watched.path.stat().st_size
    if size < watched.position:
        watched.position = 0
    with watched.path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(watched.position)
        lines = handle.readlines()
        watched.position = handle.tell()
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch Frakir/Cognee logs for errors.")
    parser.add_argument("paths", nargs="*", type=Path, default=DEFAULT_PATHS)
    parser.add_argument("--from-start", action="store_true")
    args = parser.parse_args()

    watched: dict[Path, WatchedFile] = {}
    print("Watching logs for errors. Press Ctrl+C to stop.", flush=True)

    try:
        while True:
            for path in resolve_paths(args.paths):
                if path not in watched:
                    position = 0 if args.from_start else path.stat().st_size
                    watched[path] = WatchedFile(path=path, position=position)
                    print(f"Watching {path}", flush=True)

            for item in list(watched.values()):
                for line in read_new_lines(item):
                    if ERROR_RE.search(line):
                        print(f"{item.path}: {line.rstrip()}", flush=True)

            time.sleep(1)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
