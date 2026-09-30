"""Watch the vault with watchfiles; restart with backoff on errors. Logs no paths."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

from watchfiles import Change as WfChange
from watchfiles import awatch

from ai_second_brain.vault.paths import Vault

logger = logging.getLogger("ai_second_brain.ingest")
Change = Literal["added", "modified", "deleted"]
_MAP: dict[WfChange, Change] = {
    WfChange.added: "added",
    WfChange.modified: "modified",
    WfChange.deleted: "deleted",
}


def _classify(
    vault: Vault, changes: set[tuple[WfChange, str]]
) -> tuple[list[tuple[Change, str]], bool]:
    """Note changes, plus whether a folder-level change needs a rescan."""
    batch: list[tuple[Change, str]] = []
    rescan = False
    for kind, raw in changes:
        rel = vault.rel(Path(raw))
        if rel is None:
            continue
        if vault.is_candidate(rel):
            batch.append((_MAP[kind], rel))
        elif (
            not vault.is_excluded(rel)
            and not rel.lower().endswith(".md")
            and not Path(raw).is_file()  # attachments are not folder moves
        ):
            rescan = True  # a folder move/delete hides its notes from the watcher
    return batch, rescan


async def run_watcher(
    vault: Vault,
    handle_batch: Callable[[list[tuple[Change, str]]], Awaitable[None]],
    stop_event: asyncio.Event,
    *,
    debounce_ms: int = 1600,
    on_rescan: Callable[[], None] | None = None,
) -> None:
    delay = 1.0
    while not stop_event.is_set():
        try:
            async for changes in awatch(
                vault.root, stop_event=stop_event, debounce=debounce_ms, recursive=True
            ):
                batch, rescan = _classify(vault, changes)
                if rescan and on_rescan is not None:
                    on_rescan()
                if batch:
                    try:
                        await handle_batch(sorted(set(batch)))
                    except Exception as error:  # keep watching; reconcile repairs the rest
                        logger.warning("watcher_batch_error type=%s", type(error).__name__)
                delay = 1.0
        except Exception as error:  # vault vanished, permissions, handler failure
            logger.warning("watcher_error type=%s", type(error).__name__)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, 60.0)
