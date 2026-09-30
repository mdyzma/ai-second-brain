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


@dataclass(frozen=True)
class Vault:
    root: Path
    excludes: tuple[str, ...]

    def is_candidate(self, rel: str) -> bool:
        return rel.lower().endswith(".md") and not _excluded(rel, self.excludes)

    def rel(self, path: Path) -> str | None:
        try:
            relative = path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return None
        return PurePosixPath(*relative.parts).as_posix()

    def abs(self, rel: str) -> Path:
        return self.root.joinpath(*PurePosixPath(rel).parts)

    def readable(self) -> bool:
        return self.root.is_dir() and os.access(self.root, os.R_OK | os.X_OK)

    def walk(self) -> dict[str, tuple[int, int]]:
        found: dict[str, tuple[int, int]] = {}
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            base = Path(dirpath)
            rel_dir = PurePosixPath(*base.relative_to(self.root).parts).as_posix()
            prefix = "" if rel_dir == "." else f"{rel_dir}/"
            dirnames[:] = [d for d in dirnames if not _excluded(f"{prefix}{d}/", self.excludes)]
            for name in filenames:
                rel = f"{prefix}{name}"
                if not self.is_candidate(rel):
                    continue
                path = base / name
                if path.is_symlink():
                    continue
                st = path.stat()
                found[rel] = (st.st_size, st.st_mtime_ns)
        return found
