"""Write a captured note into the vault: exclusive create, never overwrite, never outside."""

import os
import re
from datetime import datetime
from pathlib import Path

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_FORBIDDEN = re.compile(r'[\\/:*?"<>|#^\[\]]')
MAX_TITLE = 60
MAX_SUFFIX = 99
CR_LF = chr(13) + chr(10)


class CaptureNameTaken(Exception):  # noqa: N818 - domain name, mapped to a 409 code
    pass


def capture_title(text: str) -> str:
    first = next((line for line in text.splitlines() if line.strip()), "")
    title = first.strip().lstrip("#").strip()
    title = _FORBIDDEN.sub("", _CONTROL.sub(" ", title))
    title = " ".join(title.split())
    if len(title) > MAX_TITLE:
        head = title[: MAX_TITLE + 1]
        cut = head.rsplit(" ", 1)[0] if " " in head else ""
        title = cut if cut else title[:MAX_TITLE]
    title = title.rstrip(". ")
    return title or "Capture"


def write_capture(vault_root: Path, capture_dir: Path, text: str, now: datetime) -> str:
    root = vault_root.resolve()
    if not capture_dir.resolve().is_relative_to(root):  # before creating anything
        raise PermissionError("capture dir outside vault")
    capture_dir.mkdir(parents=True, exist_ok=True)
    target_dir = capture_dir.resolve()
    if capture_dir.is_symlink() or not target_dir.is_relative_to(root):
        raise PermissionError("capture dir outside vault")
    stem = f"{now:%Y-%m-%d %H%M} {capture_title(text)}"
    captured = now.isoformat(timespec="seconds")
    body = f"---\ncaptured: {captured}\nsource: app\n---\n{text.rstrip(CR_LF)}\n"
    for n in range(1, MAX_SUFFIX + 1):
        name = f"{stem}.md" if n == 1 else f"{stem} ({n}).md"
        path = target_dir / name
        try:
            with open(path, "x", encoding="utf-8", newline="\n") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            continue
        return path.relative_to(root).as_posix()
    raise CaptureNameTaken
