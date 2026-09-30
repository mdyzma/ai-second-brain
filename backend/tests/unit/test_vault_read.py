import hashlib
import unicodedata
from pathlib import Path

import pytest

from ai_second_brain.vault.read import normalize_bytes, read_note

POLISH = "Zażółć gęślą jaźń"


def test_nfc_nfd_bom_and_newlines_hash_equally() -> None:
    nfc = unicodedata.normalize("NFC", POLISH) + "\r\nline"
    nfd = unicodedata.normalize("NFD", POLISH) + "\nline"
    a = normalize_bytes(nfc.encode())
    b = normalize_bytes(b"\xef\xbb\xbf" + nfd.encode())
    c = normalize_bytes((unicodedata.normalize("NFC", POLISH) + "\rline").encode())
    assert a == b == c
    assert a[0] == unicodedata.normalize("NFC", POLISH) + "\nline"
    assert a[1] == hashlib.sha256(a[0].encode()).digest()


def test_read_note_ok(tmp_path: Path) -> None:
    path = tmp_path / "n.md"
    path.write_bytes("héllo".encode())
    note = read_note(path, max_bytes=1000)
    assert note.error is None
    assert note.text == "héllo"
    assert note.size == len("héllo".encode())
    assert note.mtime_ns == path.stat().st_mtime_ns


def test_invalid_utf8_is_encoding_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_bytes(b"\xff\xfe\x00bad")
    note = read_note(path, max_bytes=1000)
    assert (note.error, note.text) == ("encoding", "")
    assert note.content_hash == hashlib.sha256(b"\xff\xfe\x00bad").digest()


def test_too_large_is_never_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "big.md"
    path.write_bytes(b"x" * 2000)

    def refuse(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("oversized file must not be read")

    monkeypatch.setattr(Path, "read_bytes", refuse)
    note = read_note(path, max_bytes=1000)
    st = path.stat()
    assert (note.error, note.text, note.size) == ("too_large", "", 2000)
    assert note.content_hash == hashlib.sha256(f"too_large:2000:{st.st_mtime_ns}".encode()).digest()


def test_nul_character_is_encoding_error(tmp_path: Path) -> None:
    path = tmp_path / "nul.md"
    path.write_bytes(b"ab\x00cd")
    note = read_note(path, max_bytes=1000)
    assert (note.error, note.text) == ("encoding", "")
    assert note.content_hash == hashlib.sha256(b"ab\x00cd").digest()
