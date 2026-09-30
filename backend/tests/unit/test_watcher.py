import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from ai_second_brain.runtime import new_event_loop
from ai_second_brain.vault.paths import Vault
from ai_second_brain.vault.watcher import Change, run_watcher

EXCLUDES = (".obsidian/**",)


def watch(tmp_path: Path, actions: list[Callable[[], object]]) -> set[tuple[Change, str]]:
    seen: set[tuple[Change, str]] = set()

    async def handle(batch: list[tuple[Change, str]]) -> None:
        seen.update(batch)

    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(
            run_watcher(Vault(tmp_path, EXCLUDES), handle, stop, debounce_ms=100)
        )
        await asyncio.sleep(0.5)
        for action in actions:
            action()
            await asyncio.sleep(0.3)
        await asyncio.sleep(1.5)
        stop.set()
        await asyncio.wait_for(task, 5)

    loop = new_event_loop()
    try:
        loop.run_until_complete(scenario())
    finally:
        loop.close()
    return seen


def test_reports_markdown_changes_only(tmp_path: Path) -> None:
    (tmp_path / ".obsidian").mkdir()
    seen = watch(
        tmp_path,
        [
            lambda: (tmp_path / "a.md").write_text("x", encoding="utf-8"),
            lambda: (tmp_path / "a.md").write_text("y", encoding="utf-8"),
            lambda: (tmp_path / "b.txt").write_text("x", encoding="utf-8"),
            lambda: (tmp_path / ".obsidian" / "c.md").write_text("x", encoding="utf-8"),
            lambda: (tmp_path / "a.md").rename(tmp_path / "renamed.md"),
        ],
    )
    paths = {rel for _, rel in seen}
    assert "a.md" in paths and "renamed.md" in paths
    assert "b.txt" not in paths and ".obsidian/c.md" not in paths
    assert ("deleted", "a.md") in seen


def watch_with(
    tmp_path: Path,
    actions: list[Callable[[], object]],
    handle: Callable[[list[tuple[Change, str]]], Awaitable[None]],
    on_rescan: Callable[[], None] | None = None,
) -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        task = asyncio.create_task(
            run_watcher(
                Vault(tmp_path, EXCLUDES), handle, stop, debounce_ms=100, on_rescan=on_rescan
            )
        )
        await asyncio.sleep(0.5)
        for action in actions:
            action()
            await asyncio.sleep(0.6)
        await asyncio.sleep(1.5)
        stop.set()
        await asyncio.wait_for(task, 5)

    loop = new_event_loop()
    try:
        loop.run_until_complete(scenario())
    finally:
        loop.close()


def test_folder_rename_requests_rescan(tmp_path: Path) -> None:
    (tmp_path / "folder").mkdir()
    (tmp_path / "folder" / "n.md").write_text("x", encoding="utf-8")
    calls: list[int] = []

    async def handle(batch: list[tuple[Change, str]]) -> None:
        pass

    watch_with(
        tmp_path,
        [lambda: (tmp_path / "folder").rename(tmp_path / "moved")],
        handle,
        lambda: calls.append(1),
    )
    assert calls


def test_handler_error_does_not_stop_watching(tmp_path: Path) -> None:
    seen: list[list[tuple[Change, str]]] = []

    async def handle(batch: list[tuple[Change, str]]) -> None:
        seen.append(batch)
        if len(seen) == 1:
            raise RuntimeError("boom")

    watch_with(
        tmp_path,
        [
            lambda: (tmp_path / "a.md").write_text("x", encoding="utf-8"),
            lambda: (tmp_path / "b.md").write_text("x", encoding="utf-8"),
        ],
        handle,
    )
    assert len(seen) >= 2
    assert any(rel == "b.md" for _, rel in seen[-1])
