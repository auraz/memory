import pytest
from pathlib import Path

from app.memory.obsidian_importer import (
    chunk_text,
    iter_markdown_files,
    read_note_readonly,
    sanitize_note,
    validate_cognee_payload,
)


def test_iter_markdown_files_skips_obsidian_dir(tmp_path):
    (tmp_path / "note.md").write_text("hello", encoding="utf-8")
    obsidian = tmp_path / ".obsidian"
    obsidian.mkdir()
    (obsidian / "private.md").write_text("skip", encoding="utf-8")

    files = iter_markdown_files(tmp_path)

    assert files == [tmp_path.resolve() / "note.md"]


def test_iter_markdown_files_keeps_excalidraw_notes(tmp_path):
    (tmp_path / "normal.md").write_text("hello", encoding="utf-8")
    (tmp_path / "drawing.excalidraw.md").write_text("useful text", encoding="utf-8")
    (tmp_path / "tagged.md").write_text(
        "---\nexcalidraw-plugin: parsed\ntags: [excalidraw]\n---\n",
        encoding="utf-8",
    )

    files = iter_markdown_files(tmp_path)

    assert files == [
        tmp_path.resolve() / "drawing.excalidraw.md",
        tmp_path.resolve() / "normal.md",
        tmp_path.resolve() / "tagged.md",
    ]


def test_read_note_readonly(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("hello", encoding="utf-8")

    assert read_note_readonly(note) == "hello"


def test_missing_vault_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        iter_markdown_files(tmp_path / "missing")


def test_sanitize_note_drops_huge_unbroken_lines():
    encoded = "A" * 3000
    sanitized = sanitize_note(f"normal text\n{encoded}\nmore text")

    assert sanitized.content == "normal text\nmore text"
    assert sanitized.removed_lines == 1


def test_sanitize_note_drops_excalidraw_compressed_json_block():
    content = """# Excalidraw Data
## Text Elements
important text
```compressed-json
ABCDEF+/ABCDEF+/ABCDEF+/ABCDEF+/ABCDEF+/
ABCDEF+/ABCDEF+/ABCDEF+/ABCDEF+/ABCDEF+/
```
after
"""

    sanitized = sanitize_note(content)

    assert "important text" in sanitized.content
    assert "after" in sanitized.content
    assert "ABCDEF" not in sanitized.content
    assert sanitized.removed_blocks == 1


def test_sanitize_note_drops_excalidraw_comment_drawing_block():
    content = """## Text Elements
useful text
%%
## Drawing
```compressed-json
ABCDEF+/ABCDEF+/ABCDEF+/ABCDEF+/ABCDEF+/
```
%%
"""

    sanitized = sanitize_note(content)

    assert "useful text" in sanitized.content
    assert "## Drawing" not in sanitized.content
    assert "ABCDEF" not in sanitized.content
    assert sanitized.removed_blocks == 1


def test_sanitize_note_drops_unwrapped_excalidraw_drawing_section():
    content = """## Text Elements
useful text
## Drawing
```compressed-json
ABCDEF+/ABCDEF+/ABCDEF+/ABCDEF+/ABCDEF+/
```
after drawing should be removed
"""

    sanitized = sanitize_note(content)

    assert "useful text" in sanitized.content
    assert "## Drawing" not in sanitized.content
    assert "ABCDEF" not in sanitized.content
    assert "after drawing should be removed" not in sanitized.content
    assert sanitized.removed_blocks == 1


def test_real_failing_excalidraw_file_keeps_text_and_drops_payload():
    path = Path(
        "../../1.Stable/ExpressionVault/Areas/Personality/Psychology/"
        "Drawing 2025-05-07 22.13.16.excalidraw.md"
    )
    if not path.exists():
        pytest.skip("Local ExpressionVault fixture is not available.")

    raw = read_note_readonly(path)
    sanitized = sanitize_note(raw)
    chunks = chunk_text(sanitized.content)

    assert "Здорова частка" in sanitized.content
    assert "## Drawing" not in sanitized.content
    assert "compressed-json" not in sanitized.content
    assert "6D9gcQM5g6kk" not in sanitized.content
    assert chunks
    assert max(len(chunk) for chunk in chunks) <= 6000


def test_real_second_excalidraw_file_keeps_text_and_drops_payload():
    path = Path(
        "../../1.Stable/ExpressionVault/Projects/EM/my EM book/"
        "Drawing 2024-05-18 15.55.28.excalidraw.md"
    )
    if not path.exists():
        pytest.skip("Local ExpressionVault fixture is not available.")

    raw = read_note_readonly(path)
    sanitized = sanitize_note(raw)

    assert "Naive project management" in sanitized.content
    assert "## Drawing" not in sanitized.content
    assert "compressed-json" not in sanitized.content
    assert "N4KAkARALgngDgUwgLgAQQQDwMYEMA2" not in sanitized.content


def test_chunk_text_splits_long_notes():
    chunks = chunk_text("a" * 10 + "\n\n" + "b" * 10, max_chars=15)

    assert chunks == ["aaaaaaaaaa", "bbbbbbbbbb"]


def test_validate_cognee_payload_rejects_drawing_markers():
    with pytest.raises(ValueError):
        validate_cognee_payload("## Drawing\n```compressed-json\nabc")


def test_validate_cognee_payload_rejects_long_tokens():
    with pytest.raises(ValueError):
        validate_cognee_payload("x" * 8192)
