"""Read and normalize one note. Never logs content."""

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReadNote:
    text: str  # '' when error is set
    content_hash: bytes
    size: int
    mtime_ns: int
    error: str | None  # 'too_large' | 'encoding' | None


def normalize_bytes(data: bytes) -> tuple[str, bytes]:
    text = data.decode("utf-8")  # raises UnicodeDecodeError
    text = text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    return text, hashlib.sha256(text.encode("utf-8")).digest()


def read_note(path: Path, max_bytes: int) -> ReadNote:
    """Raises OSError on I/O failure (the caller maps it to io_error)."""
    st = path.stat()
    if st.st_size > max_bytes:
        marker = f"too_large:{st.st_size}:{st.st_mtime_ns}".encode()
        digest = hashlib.sha256(marker).digest()
        return ReadNote("", digest, st.st_size, st.st_mtime_ns, "too_large")
    data = path.read_bytes()
    try:
        text, digest = normalize_bytes(data)
    except UnicodeDecodeError:
        return ReadNote("", hashlib.sha256(data).digest(), st.st_size, st.st_mtime_ns, "encoding")
    return ReadNote(text, digest, st.st_size, st.st_mtime_ns, None)
