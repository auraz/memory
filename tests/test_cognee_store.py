import pytest

from app.memory.cognee_store import CogneeMemory


def test_reset_storage_directories_removes_cognee_files(tmp_path, monkeypatch):
    roots = {
        "SYSTEM_ROOT_DIRECTORY": tmp_path / "data" / "cognee" / "system",
        "DATA_ROOT_DIRECTORY": tmp_path / "data" / "cognee" / "storage",
        "CACHE_ROOT_DIRECTORY": tmp_path / "data" / "cognee" / "cache",
    }
    for key, path in roots.items():
        monkeypatch.setenv(key, str(path))
        path.mkdir(parents=True)
        (path / "stale.txt").write_text("old graph data", encoding="utf-8")

    memory = object.__new__(CogneeMemory)
    memory._reset_storage_directories()

    for path in roots.values():
        assert path.exists()
        assert list(path.iterdir()) == []


def test_reset_storage_directories_rejects_unsafe_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("SYSTEM_ROOT_DIRECTORY", str(tmp_path / "system"))
    monkeypatch.setenv("DATA_ROOT_DIRECTORY", str(tmp_path / "data" / "cognee" / "storage"))
    monkeypatch.setenv("CACHE_ROOT_DIRECTORY", str(tmp_path / "data" / "cognee" / "cache"))

    memory = object.__new__(CogneeMemory)

    with pytest.raises(RuntimeError):
        memory._reset_storage_directories()
