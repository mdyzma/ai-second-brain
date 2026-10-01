from pathlib import Path

import pytest

from ..e2e_reset import clear_capture_dir


def fixture_vault(tmp_path: Path) -> Path:
    vault = tmp_path.joinpath("repo", "web", "tests", "e2e", "fixtures", "vault")
    vault.mkdir(parents=True)
    (vault / "NAS.md").write_text("# NAS\n", encoding="utf-8")
    return vault


def test_clears_the_fixture_inbox(tmp_path: Path) -> None:
    vault = fixture_vault(tmp_path)
    (vault / "Inbox").mkdir()
    (vault / "Inbox" / "capture.md").write_text("x", encoding="utf-8")
    assert clear_capture_dir(str(vault)) is True
    assert not (vault / "Inbox").exists()
    assert (vault / "NAS.md").exists()


def test_missing_inbox_is_fine(tmp_path: Path) -> None:
    assert clear_capture_dir(str(fixture_vault(tmp_path))) is True


def test_refuses_a_vault_that_is_not_the_fixture(tmp_path: Path) -> None:
    vault = tmp_path / "Brain"
    (vault / "Inbox").mkdir(parents=True)
    (vault / "Inbox" / "real.md").write_text("keep", encoding="utf-8")
    assert clear_capture_dir(str(vault)) is False
    assert (vault / "Inbox" / "real.md").exists()


def test_refuses_an_inbox_that_is_a_file(tmp_path: Path) -> None:
    vault = fixture_vault(tmp_path)
    (vault / "Inbox").write_text("not a folder", encoding="utf-8")
    assert clear_capture_dir(str(vault)) is False
    assert (vault / "Inbox").is_file()


def test_refuses_a_symlinked_inbox(tmp_path: Path) -> None:
    vault = fixture_vault(tmp_path)
    outside = tmp_path / "real-inbox"
    outside.mkdir()
    (outside / "keep.md").write_text("keep", encoding="utf-8")
    try:
        (vault / "Inbox").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need extra privileges on this machine")
    assert clear_capture_dir(str(vault)) is False
    assert (outside / "keep.md").exists()


def test_rmtree_errors_surface(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = fixture_vault(tmp_path)
    (vault / "Inbox").mkdir()

    def boom(path: Path) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr("tests.e2e_reset.shutil.rmtree", boom)
    with pytest.raises(PermissionError):
        clear_capture_dir(str(vault))
