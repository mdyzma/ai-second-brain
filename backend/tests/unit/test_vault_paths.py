import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from ai_second_brain.vault.paths import Vault

from ..vaults import VaultBuilder

EXCLUDES = (".obsidian/**", ".trash/**", "**/.git/**")


def test_candidates_are_markdown_outside_excludes(tmp_path: Path) -> None:
    vault = Vault(tmp_path, EXCLUDES)
    assert vault.is_candidate("Notes/a.md")
    assert vault.is_candidate("Notes/A.MD")
    assert not vault.is_candidate("Notes/a.txt")
    assert not vault.is_candidate(".obsidian/workspace.md")
    assert not vault.is_candidate(".trash/old.md")
    assert not vault.is_candidate(".git/x.md")
    assert not vault.is_candidate("Projects/.git/x.md")


def test_rel_path_keeps_unicode_and_spaces(tmp_path: Path) -> None:
    vault = Vault(tmp_path, EXCLUDES)
    path = tmp_path / "Notatki" / "Zażółć gęślą.md"
    assert vault.rel(path) == "Notatki/Zażółć gęślą.md"
    assert vault.abs("Notatki/Zażółć gęślą.md") == path
    assert vault.rel(tmp_path.parent / "outside.md") is None


def test_walk_lists_candidates_with_size_and_mtime(tmp_path: Path) -> None:
    builder = VaultBuilder(tmp_path)
    builder.write("a.md", "alpha", mtime_ns=1_700_000_000_000_000_000)
    builder.write("Sub/b.md", "bravo!")
    builder.write(".obsidian/c.md", "x")
    builder.write("Sub/d.txt", "x")
    walked = Vault(tmp_path, EXCLUDES).walk()
    assert set(walked) == {"a.md", "Sub/b.md"}
    assert walked["a.md"] == (5, 1_700_000_000_000_000_000)
    assert walked["Sub/b.md"][0] == 6


def test_readable(tmp_path: Path) -> None:
    assert Vault(tmp_path, EXCLUDES).readable()
    assert not Vault(tmp_path / "missing", EXCLUDES).readable()


def test_walk_skips_file_that_vanishes_before_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = VaultBuilder(tmp_path)
    builder.write("keep.md", "k")
    builder.write("gone.md", "g")
    real_stat = Path.stat

    def flaky(self: Path, *args: Any, **kwargs: Any) -> os.stat_result:
        if self.name == "gone.md":
            raise FileNotFoundError(str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky)
    assert set(Vault(tmp_path, EXCLUDES).walk()) == {"keep.md"}


def test_walk_raises_when_a_directory_cannot_be_listed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    VaultBuilder(tmp_path).write("a.md", "a")
    real_walk = os.walk

    def failing(*args: Any, onerror: Any = None, **kwargs: Any) -> Iterator[Any]:
        assert onerror is not None
        onerror(PermissionError("denied"))
        yield from real_walk(*args, **kwargs)

    monkeypatch.setattr(os, "walk", failing)
    with pytest.raises(OSError, match="denied"):
        Vault(tmp_path, EXCLUDES).walk()


def test_rel_keeps_the_event_file_name_case(tmp_path: Path) -> None:
    (tmp_path / "Dir").mkdir()
    (tmp_path / "Dir" / "note.md").write_text("x", encoding="utf-8")
    vault = Vault(tmp_path, ())
    # on a case-insensitive disk resolve() would rewrite this to the on-disk "note.md"
    assert vault.rel(tmp_path / "Dir" / "Note.md") == "Dir/Note.md"


def test_exists_exact_matches_the_name_case(tmp_path: Path) -> None:
    (tmp_path / "note.md").write_text("x", encoding="utf-8")
    (tmp_path / "folder.md").mkdir()
    vault = Vault(tmp_path, ())
    assert vault.exists_exact("note.md")
    assert not vault.exists_exact("Note.md")
    assert not vault.exists_exact("missing.md")
    assert not vault.exists_exact("nowhere/note.md")
    assert not vault.exists_exact("folder.md")  # a directory is not a note
