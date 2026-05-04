import asyncio

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


def test_reset_skips_cognee_api_when_database_is_absent(tmp_path, monkeypatch):
    roots = {
        "SYSTEM_ROOT_DIRECTORY": tmp_path / "data" / "cognee" / "system",
        "DATA_ROOT_DIRECTORY": tmp_path / "data" / "cognee" / "storage",
        "CACHE_ROOT_DIRECTORY": tmp_path / "data" / "cognee" / "cache",
    }
    for key, path in roots.items():
        monkeypatch.setenv(key, str(path))
        path.mkdir(parents=True)

    class FakeCognee:
        def __init__(self):
            self.called = False

        async def forget(self, everything=False):
            self.called = True

    fake = FakeCognee()
    memory = object.__new__(CogneeMemory)
    memory._cognee = fake

    asyncio.run(memory.reset())

    assert fake.called is False


def test_has_local_cognee_database_detects_database_files(tmp_path, monkeypatch):
    system = tmp_path / "data" / "cognee" / "system"
    monkeypatch.setenv("SYSTEM_ROOT_DIRECTORY", str(system))
    memory = object.__new__(CogneeMemory)

    assert memory._has_local_cognee_database() is False

    database = system / "databases" / "cognee_db"
    database.parent.mkdir(parents=True)
    database.write_text("", encoding="utf-8")

    assert memory._has_local_cognee_database() is True
