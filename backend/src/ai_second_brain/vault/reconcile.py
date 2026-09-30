"""One reconcile pass: vault <-> database, moves, tombstones (guarded), and recovery."""

import asyncio
import logging
from dataclasses import asdict, dataclass

import psycopg

from ai_second_brain.knowledge import store
from ai_second_brain.knowledge.context import IngestContext
from ai_second_brain.vault.moves import guard_trips, pair_moves
from ai_second_brain.vault.observe import observe
from ai_second_brain.vault.read import read_note

logger = logging.getLogger("ai_second_brain.ingest")
STALLED_SECONDS = 600
# pg_advisory_xact_lock key serialising the move + tombstone phase across processes
MOVES_LOCK_KEY = 0x5EC0_B7A1_0001


@dataclass
class ReconcileCounts:
    seen: int = 0
    new: int = 0
    changed: int = 0
    moved: int = 0
    missing: int = 0
    tombstoned: int = 0
    requeued_index: int = 0
    requeued_embed: int = 0
    stalled_reset: int = 0
    io_error: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


async def _hash(ctx: IngestContext, rel: str) -> bytes | None:
    if ctx.vault is None:
        return None
    try:
        note = await asyncio.to_thread(read_note, ctx.vault.abs(rel), ctx.settings.max_note_bytes)
    except OSError:
        return None
    return note.content_hash


@dataclass
class MoveResult:
    tripped: bool
    moved: int
    missing: int
    tombstoned: int
    to_observe: list[str]


async def _still_on_disk(ctx: IngestContext, rel: str) -> bool:
    return ctx.vault is not None and await asyncio.to_thread(ctx.vault.exists_exact, rel)


async def apply_moves_and_deletes(
    ctx: IngestContext,
    deleted: dict[str, bytes | None],
    added: dict[str, bytes],
    *,
    guard: bool,
    allow_mass_delete: bool,
) -> MoveResult:
    """`deleted` maps a vanished path to its snapshot hash (None never pairs: tombstone only)."""
    moved = 0
    async with ctx.pool.connection() as conn, conn.transaction():
        # One mover at a time (watcher batch vs reconcile, any process), and a live snapshot
        # that can't change under us.
        await conn.execute("SELECT pg_advisory_xact_lock(%s)", (MOVES_LOCK_KEY,))
        live = await store.live_sources(conn)
        # the caller's snapshot may be older than ours; skip anything no longer live
        deleted = {rel: digest for rel, digest in deleted.items() if rel in live}
        pairs, gone, rest = pair_moves(deleted, added)
        for old, new in pairs:
            if not await store.path_taken(conn, new):
                try:
                    async with conn.transaction():  # savepoint: a collision keeps the rest
                        await store.move_source(conn, live[old].source_id, new)
                except psycopg.errors.UniqueViolation:
                    pass  # a concurrent observe took `new`; its DETAIL holds a path: never log it
                else:
                    moved += 1
                    continue
            gone.append(old)
            rest.append(new)
        # the listing may be stale: never tombstone a path that is back on disk
        gone = [rel for rel in gone if not await _still_on_disk(ctx, rel)]
        if guard and not allow_mass_delete and guard_trips(len(gone), len(live)):
            return MoveResult(True, moved, len(gone), 0, sorted(rest))
        for rel in gone:
            await store.tombstone(conn, live[rel].source_id)
    return MoveResult(False, moved, len(gone), len(gone), sorted(rest))


async def reconcile(
    ctx: IngestContext, *, trigger: str, run_id: int | None = None, allow_mass_delete: bool = False
) -> tuple[str, ReconcileCounts]:
    counts = ReconcileCounts()
    async with ctx.pool.connection() as conn:
        if run_id is None:
            run_id = await store.start_run(conn, trigger)
        await store.mark_picked_up(conn, run_id)  # a queued manual run is now running
    outcome = "ok"
    try:
        if ctx.vault is None:
            outcome = "disabled"
            return outcome, counts
        if not await asyncio.to_thread(ctx.vault.readable):
            outcome = "vault_unavailable"
            return outcome, counts
        # A source that became live while we walked (a watcher batch observed or moved it) is
        # absent from the listing but not missing: only sources live before the walk can be.
        async with ctx.pool.connection() as conn:
            live_before = await store.live_sources(conn)
        try:
            on_disk = await asyncio.to_thread(ctx.vault.walk)
        except OSError:  # includes VaultWalkError: a partial walk must never tombstone anything
            outcome = "vault_unavailable"
            return outcome, counts
        counts.seen = len(on_disk)
        async with ctx.pool.connection() as conn:
            live = await store.live_sources(conn)
        new_paths = [rel for rel in on_disk if rel not in live]
        changed = [
            rel
            for rel, (size, mtime) in on_disk.items()
            if rel in live and (live[rel].size, live[rel].mtime_ns) != (size, mtime)
        ]
        # snapshot-less (failed-only) sources can't pair as moves, but still get tombstoned
        missing = {
            rel: s.snapshot_hash
            for rel, s in live.items()
            if rel in live_before and rel not in on_disk
        }
        added_hashes = {rel: h for rel in new_paths if (h := await _hash(ctx, rel)) is not None}
        result = await apply_moves_and_deletes(
            ctx, missing, added_hashes, guard=True, allow_mass_delete=allow_mass_delete
        )
        counts.moved, counts.missing, counts.tombstoned = (
            result.moved,
            result.missing,
            result.tombstoned,
        )
        if result.tripped:
            outcome = "guard_tripped"
        for rel in [*result.to_observe, *changed]:
            observed = await observe(ctx, rel)
            if observed is None:
                counts.io_error += 1
            elif rel in changed:
                counts.changed += 1
            else:
                counts.new += 1
        # Reset stalled jobs before re-deferring: retrying a stalled job would collide with
        # the queueing lock of a freshly re-deferred twin.
        counts.stalled_reset = await ctx.queue.reset_stalled(STALLED_SECONDS)
        async with ctx.pool.connection() as conn:
            pending = await store.pending_sources(conn)
            missing_vectors = await store.revisions_missing_embeddings(conn, ctx.space_id)
        for source_id in pending:
            await ctx.queue.index_source(source_id)
        for revision_id in missing_vectors:
            await ctx.queue.embed_revision(revision_id, ctx.space_id)
        counts.requeued_index, counts.requeued_embed = len(pending), len(missing_vectors)
        return outcome, counts
    except BaseException as error:
        outcome = (
            "interrupted"
            if isinstance(error, asyncio.CancelledError)
            else (f"error:{type(error).__name__}")
        )
        raise
    finally:
        try:
            async with ctx.pool.connection() as conn:
                await store.finish_run(conn, run_id, outcome, counts.as_dict())
        except Exception as record_error:  # never mask the original outcome
            logger.error(
                "reconcile run=%s could not record outcome: %s", run_id, type(record_error).__name__
            )
        logger.info(
            "reconcile run=%s trigger=%s outcome=%s counts=%s",
            run_id,
            trigger,
            outcome,
            counts.as_dict(),
        )
