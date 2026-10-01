from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ai_second_brain.vault.capture import CaptureNameTaken, capture_title, write_capture

NOW = datetime(2026, 10, 1, 14, 32, 5, tzinfo=timezone(timedelta(hours=2)))


@pytest.mark.parametrize(
    ("text", "title"),
    [
        ("Check NAS backup schedule\nmore", "Check NAS backup schedule"),
        ("\n\n  # Heading line  \nbody", "Heading line"),
        ('a\\b/c:d*e?f"g<h>i|j#k^l[m]n', "abcdefghijklmn"),
        ("Zażółć gęślą jaźń", "Zażółć gęślą jaźń"),
        ("word " * 30, "word word word word word word word word word word word word"),
        ("...", "Capture"),
        ("   \n  ", "Capture"),
        ("trailing dots...", "trailing dots"),
        ("tab\tand\x07bell", "tab and bell"),
    ],
)
def test_capture_title(text: str, title: str) -> None:
    assert capture_title(text) == title


@pytest.mark.parametrize("first", ["../../etc/passwd", "C:\\x\\y", "Projects/a", "/abs"])
def test_title_cannot_escape_capture_dir(tmp_path: Path, first: str) -> None:
    rel = write_capture(tmp_path, tmp_path / "Inbox", f"{first}\nbody", NOW)
    assert rel.startswith("Inbox/") and rel.count("/") == 1
    assert (tmp_path / rel).is_file()


def test_write_capture_content_and_collisions(tmp_path: Path) -> None:
    first = write_capture(tmp_path, tmp_path / "Inbox", "Idea\nbody", NOW)
    second = write_capture(tmp_path, tmp_path / "Inbox", "Idea\nother", NOW)
    assert first == "Inbox/2026-10-01 1432 Idea.md"
    assert second == "Inbox/2026-10-01 1432 Idea (2).md"
    content = (tmp_path / first).read_bytes().decode("utf-8")
    assert content == "---\ncaptured: 2026-10-01T14:32:05+02:00\nsource: app\n---\nIdea\nbody\n"


def test_write_capture_gives_up_after_99(tmp_path: Path) -> None:
    inbox = tmp_path / "Inbox"
    inbox.mkdir()
    (inbox / "2026-10-01 1432 Idea.md").write_text("x")
    for i in range(2, 100):
        (inbox / f"2026-10-01 1432 Idea ({i}).md").write_text("x")
    with pytest.raises(CaptureNameTaken):
        write_capture(tmp_path, inbox, "Idea", NOW)


def test_symlinked_capture_dir_outside_vault_is_refused(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    vault = tmp_path / "vault"
    vault.mkdir()
    try:
        (vault / "Inbox").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need extra privileges on this platform")
    with pytest.raises(OSError):
        write_capture(vault, vault / "Inbox", "x", NOW)
    assert not any(outside.iterdir())
