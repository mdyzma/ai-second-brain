"""Vault root, exclusions and candidate files (vault-relative POSIX paths)."""

import os
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath


def _excluded(rel: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if fnmatchcase(rel, pattern):
            return True
        if pattern.startswith("**/") and fnmatchcase(rel, pattern[3:]):
            return True
    return False


class VaultWalkError(OSError):
    """A directory could not be listed; the walk result would be incomplete."""


@dataclass(frozen=True)
class Vault:
    root: Path
    excludes: tuple[str, ...]

    def is_candidate(self, rel: str) -> bool:
        return rel.lower().endswith(".md") and not _excluded(rel, self.excludes)

    def is_excluded(self, rel: str) -> bool:
        return _excluded(rel, self.excludes)

    def rel(self, path: Path) -> str | None:
        # Resolve the parent only: on a case-insensitive disk resolving the file itself would
        # rewrite a case-only rename's `deleted Note.md` event to the new on-disk `note.md`.
        try:
            relative = (path.parent.resolve() / path.name).relative_to(self.root.resolve())
        except ValueError:
            return None
        return PurePosixPath(*relative.parts).as_posix()

    def abs(self, rel: str) -> Path:
        return self.root.joinpath(*PurePosixPath(rel).parts)

    def exists_exact(self, rel: str) -> bool:
        """The file exists under exactly this name's case (is_file() ignores case on NTFS/APFS)."""
        path = self.abs(rel)
        try:
            return path.name in os.listdir(path.parent) and path.is_file()
        except OSError:
            return False

    def readable(self) -> bool:
        return self.root.is_dir() and os.access(self.root, os.R_OK | os.X_OK)

    def walk(self) -> dict[str, tuple[int, int]]:
        found: dict[str, tuple[int, int]] = {}
        errors: list[OSError] = []
        for dirpath, dirnames, filenames in os.walk(
            self.root, followlinks=False, onerror=errors.append
        ):
            base = Path(dirpath)
            rel_dir = PurePosixPath(*base.relative_to(self.root).parts).as_posix()
            prefix = "" if rel_dir == "." else f"{rel_dir}/"
            dirnames[:] = [d for d in dirnames if not _excluded(f"{prefix}{d}/", self.excludes)]
            for name in filenames:
                rel = f"{prefix}{name}"
                if not self.is_candidate(rel):
                    continue
                path = base / name
                try:
                    if path.is_symlink():
                        continue
                    st = path.stat()
                except OSError:
                    continue  # vanished or unreadable mid-walk: skip this file
                found[rel] = (st.st_size, st.st_mtime_ns)
        if errors:
            raise VaultWalkError(f"could not list {len(errors)} vault directories: {errors[0]}")
        return found
