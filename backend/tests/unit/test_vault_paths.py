from pathlib import Path

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
