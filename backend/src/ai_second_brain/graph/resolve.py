"""Resolution (spec §6): extracted names -> entities, then reviewable edges.

`resolve` only reads and writes the database; it runs inside the transaction that records the
extraction (the source row is locked). Name vectors for the similarity step are computed first,
outside any transaction, by `embed_names`, so the lock is never held across a network call.
New entities are returned so the caller can queue their embeddings after the commit.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from ai_second_brain.graph import store
from ai_second_brain.graph.context import GraphContext
from ai_second_brain.graph.names import norm
from ai_second_brain.graph.rules import MatchKind, initial_edge_status
from ai_second_brain.graph.schema import ExtractionOutput
from ai_second_brain.knowledge.store import default_space

NOTE = "NOTE"
NameVectors = Mapping[tuple[str, str], list[float]]  # (type, norm(name)) -> query vector

_MATCH_RANK: dict[MatchKind, int] = {"exact": 3, "alias": 3, "similar": 1, "new": 0}


@dataclass(frozen=True)
class ResolveCounts:
    created: int
    linked: int
    accepted: int
    proposed: int
    dropped: int
    created_ids: tuple[UUID, ...] = ()  # queue `embed_entity` for these after the commit


@dataclass
class _Mention:
    entity: store.EntityRow
    match: MatchKind
    confidence: float
    evidence: UUID | None
    about: bool

    @property
    def relation(self) -> str:
        return "about" if self.about else "mentions"


def _parse(output: Mapping[str, Any]) -> tuple[ExtractionOutput, dict[str, str]]:
    merged = ExtractionOutput.model_validate(
        {
            k: output.get(k, "" if k == "summary" else [])
            for k in ("summary", "entities", "relations")
        }
    )
    evidence = output.get("evidence")
    return merged, (evidence if isinstance(evidence, dict) else {})


def _chunk(evidence: Mapping[str, str], key: list[str]) -> UUID | None:
    value = evidence.get(json.dumps(key))
    try:
        return UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


async def embed_names(
    ctx: GraphContext, output: ExtractionOutput
) -> dict[tuple[str, str], list[float]]:
    """Query vectors for names with no exact/alias hit. Call outside any transaction.

    Empty when there is no embedder or it is down (the breaker makes later calls return fast).
    """
    if ctx.names is None or not output.entities:
        return {}
    pending: list[tuple[str, str, str]] = []
    async with ctx.pool.connection() as conn:
        for ent in output.entities:
            keys = [norm(ent.name), *(norm(a) for a in ent.aliases)]
            hits = [await store.find_by_name(conn, ent.type, k) for k in keys if k]
            if not any(hits):
                pending.append((ent.type, norm(ent.name), ent.name))
    vectors: dict[tuple[str, str], list[float]] = {}
    for type_, key, name in pending:
        vector = await ctx.names.embed(name)
        if vector is not None:
            vectors[(type_, key)] = vector
    return vectors


async def resolve(
    conn: AsyncConnection,
    ctx: GraphContext,
    *,
    source_id: UUID,
    revision_id: UUID,
    output: Mapping[str, Any],
    vectors: NameVectors | None = None,
) -> ResolveCounts:
    merged, evidence = _parse(output)
    model = ctx.client.model if ctx.client is not None else "unknown"
    origin = f"llm:{model}"
    threshold = ctx.settings.extract_auto_accept
    vectors = vectors or {}
    space: tuple[int, int] | None = None
    if vectors:
        space_id, _model, dims = await default_space(conn)
        space = (space_id, dims)

    about = {
        norm(r.object) for r in merged.relations if r.subject == NOTE and r.relation == "about"
    }
    # Relation endpoints are looked up by norm: entity names first, then their aliases.
    # None marks a name that resolved to a rejected entity (dropped with its relations).
    by_name: dict[str, store.EntityRow | None] = {}
    by_alias: dict[str, store.EntityRow | None] = {}
    mentions: dict[UUID, _Mention] = {}
    created_ids: list[UUID] = []
    linked = dropped = 0

    # A stable lock order (type, norm(name)) so two notes never take entity locks crosswise.
    for ent in sorted(merged.entities, key=lambda e: (e.type, norm(e.name))):
        key = norm(ent.name)
        alias_keys = [k for k in (norm(a) for a in ent.aliases) if k]
        hit: tuple[store.EntityRow, MatchKind] | None = None
        for candidate in [key, *alias_keys]:
            hit = await store.find_by_name(conn, ent.type, candidate) if candidate else None
            if hit is not None:
                break
        if hit is None and space is not None:
            vector = vectors.get((ent.type, key))
            if vector is not None and len(vector) == space[1]:
                near = await store.nearest_by_embedding(
                    conn,
                    ent.type,
                    vector,
                    space_id=space[0],
                    dims=space[1],
                    min_similarity=ctx.settings.entity_match_similarity,
                )
                if near is not None:
                    hit = (near[0], "similar")
        if hit is None:
            row = await store.create_entity(conn, ent.type, ent.name, ent.aliases)
            # On a (type, norm_name) conflict (a concurrent note won) it is an exact match.
            hit = (row, "new" if row.inserted else "exact")
        entity, match = hit
        if entity.status == "rejected":
            by_name.setdefault(key, None)
            for alias_key in alias_keys:
                by_alias.setdefault(alias_key, None)
            dropped += 1
            continue
        if match == "similar":
            await store.add_suggested_alias(conn, entity.id, ent.name)
        if match == "new":
            created_ids.append(entity.id)
        else:
            linked += 1
        by_name.setdefault(key, entity)
        for alias_key in alias_keys:
            by_alias.setdefault(alias_key, entity)
        mention = _Mention(
            entity,
            match,
            ent.confidence,
            _chunk(evidence, ["entity", ent.type, key]),
            key in about,
        )
        kept = mentions.get(entity.id)
        if kept is None:
            mentions[entity.id] = mention
        else:  # two extracted names resolved to one entity: keep the strongest claim
            if _MATCH_RANK[match] > _MATCH_RANK[kept.match]:
                kept.match = match
            kept.confidence = max(kept.confidence, mention.confidence)
            kept.evidence = kept.evidence or mention.evidence
            kept.about = kept.about or mention.about

    def lookup(name: str) -> tuple[bool, store.EntityRow | None]:
        """(known, entity); known with entity None means the name was dropped."""
        if name in by_name:
            return True, by_name[name]
        if name in by_alias:
            return True, by_alias[name]
        return False, None

    await store.replace_machine_edges(conn, source_id)
    # Edges are written in (src_type, src_id, relation, dst_entity_id) order: entity edges
    # first, then this note's mention edges, then parent proposals.

    links: dict[tuple[UUID, str, UUID], tuple[float, UUID | None]] = {}
    for rel in merged.relations:
        subject, obj = norm(rel.subject), norm(rel.object)
        (s_known, src), (o_known, dst) = lookup(subject), lookup(obj)
        if (s_known and src is None) or (o_known and dst is None):
            dropped += 1  # a relation naming a rejected entity is dropped with it
            continue
        if rel.subject == NOTE or src is None or dst is None or src.id == dst.id:
            continue  # NOTE relations became the mention edges; self-loops are dropped
        link = (src.id, rel.relation, dst.id)
        chunk = _chunk(evidence, [subject, rel.relation, obj])
        previous = links.get(link)
        if previous is None:
            links[link] = (rel.confidence, chunk)
        else:
            links[link] = (max(previous[0], rel.confidence), previous[1] or chunk)
    parents: list[tuple[UUID, UUID]] = []
    for (src_id, relation, dst_id), (confidence, chunk) in sorted(links.items()):
        await store.upsert_edge(
            conn,
            src_type="entity",
            src_id=src_id,
            relation=relation,
            dst_entity_id=dst_id,
            confidence=confidence,
            origin=origin,
            status="proposed",
            evidence_chunk_id=chunk,
            revision_id=revision_id,
        )
        if relation == "part_of":
            parents.append((src_id, dst_id))
    accepted = 0
    proposed = len(links)
    for mention in sorted(mentions.values(), key=lambda m: (m.relation, m.entity.id)):
        status = initial_edge_status(
            match=mention.match,
            entity_status=mention.entity.status,
            confidence=mention.confidence,
            threshold=threshold,
        )
        await store.upsert_edge(
            conn,
            src_type="source",
            src_id=source_id,
            relation=mention.relation,
            dst_entity_id=mention.entity.id,
            confidence=mention.confidence,
            origin=origin,
            status=status,
            evidence_chunk_id=mention.evidence,
            revision_id=revision_id,
        )
        if status == "accepted":
            accepted += 1
        else:
            proposed += 1

    for child_id, parent_id in parents:
        await store.set_proposed_parent(conn, child_id, parent_id)

    return ResolveCounts(
        created=len(created_ids),
        linked=linked,
        accepted=accepted,
        proposed=proposed,
        dropped=dropped,
        created_ids=tuple(created_ids),
    )
