import os

import pytest

from app.memory.cognee_store import CogneeMemory, MemoryItem


def test_normalize_cognee_dict_result():
    memory = object.__new__(CogneeMemory)

    normalized = memory._normalize(
        [{"search_result": ["one", "two"], "dataset_name": "main_dataset", "_source": "graph"}]
    )

    assert normalized == [MemoryItem(text="one\ntwo", source="graph:main_dataset")]


def test_reset_storage_directories_rejects_unsafe_paths(tmp_path):
    old = {
        key: os.environ.get(key)
        for key in ("SYSTEM_ROOT_DIRECTORY", "DATA_ROOT_DIRECTORY", "CACHE_ROOT_DIRECTORY")
    }
    try:
        os.environ["SYSTEM_ROOT_DIRECTORY"] = str(tmp_path / "system")
        os.environ["DATA_ROOT_DIRECTORY"] = str(tmp_path / "data" / "cognee" / "storage")
        os.environ["CACHE_ROOT_DIRECTORY"] = str(tmp_path / "data" / "cognee" / "cache")
        memory = object.__new__(CogneeMemory)

        with pytest.raises(RuntimeError):
            memory._reset_storage_directories()
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
