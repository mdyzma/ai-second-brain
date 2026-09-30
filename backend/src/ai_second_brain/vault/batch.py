"""Apply one watcher batch: pair moves, tombstone (guarded), observe the rest."""

import asyncio
import logging

from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.vault.observe import observe
from ai_second_brain.vault.read import read_note
from ai_second_brain.vault.reconcile import apply_moves_and_deletes
from ai_second_brain.vault.watcher import Change

logger = logging.getLogger("ai_second_brain.ingest")


async def apply_batch(ctx: IngestContext, changes: list[tuple[Change, str]]) -> None:
    if ctx.vault is None:
        raise RuntimeError("vault is not configured")
    vault = ctx.vault
    # exact case: a case-only rename must read as `deleted Note.md` + `added note.md`
    exists = {
        rel: await asyncio.to_thread(vault.exists_exact, rel) for rel in {r for _, r in changes}
    }
    deleted_rels = {rel for kind, rel in changes if kind == "deleted" and not exists[rel]}
    touched = {rel for _, rel in changes if exists[rel]}
    async with ctx.pool.connection() as conn:
        live = await store.live_sources(conn)
    deleted: dict[str, bytes] = {}
    for rel in deleted_rels:
        if rel in live and (snapshot := live[rel].snapshot_hash):
            deleted[rel] = snapshot
    new_hashes: dict[str, bytes] = {}
    for rel in sorted(touched - set(live)):
        try:
            note = await asyncio.to_thread(
                read_note, ctx.vault.abs(rel), ctx.settings.max_note_bytes
            )
        except OSError:
            continue
        new_hashes[rel] = note.content_hash
    result = await apply_moves_and_deletes(
        ctx, deleted, new_hashes, guard=True, allow_mass_delete=False
    )
    if result.tripped:
        logger.warning("batch_guard_tripped missing=%d", result.missing)
    for rel in sorted(set(result.to_observe) | (touched & set(live))):
        await observe(ctx, rel)
