"""Graph routes (spec §8): extraction status and runs, the review queues, entity pages."""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from psycopg import AsyncConnection
from psycopg.errors import DeadlockDetected, SerializationFailure

from ai_second_brain.graph import decide, queries
from ai_second_brain.graph import store as graph_store
from ai_second_brain.graph.prompt import EXTRACTOR_VERSION
from ai_second_brain.interfaces.api.deps import get_settings, require_same_origin, require_session
from ai_second_brain.interfaces.api.schemas import (
    EntityDecided,
    EntityDecision,
    EntityDetail,
    EntityPage,
    EntityType,
    ErrorResponse,
    ExtractQueued,
    GraphExtractRequest,
    GraphStatus,
    LinkDecisions,
    LinksUpdated,
    ReviewEntityPage,
    ReviewLinkPage,
)
from ai_second_brain.knowledge.status import InvalidCursorError

logger = logging.getLogger("ai_second_brain.api")

router = APIRouter(tags=["graph"], dependencies=[Depends(require_session)])
ERRORS: dict[int | str, dict[str, Any]] = {
    k: {"model": ErrorResponse} for k in (401, 403, 422, 503)
}
DECISION_STATUS = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "name_taken": status.HTTP_409_CONFLICT,
    "parent_cycle": 422,
    "type_mismatch": 422,
    "invalid_action": 422,
}
Cursor = Annotated[str | None, Query(max_length=500)]


def _vault_name(request: Request) -> str:
    return get_settings(request).obsidian_vault_name


def _invalid_cursor() -> HTTPException:
    return HTTPException(422, detail="invalid_cursor")


@router.get(
    "/graph/status", operation_id="graphStatus", response_model=GraphStatus, responses=ERRORS
)
async def graph_status(request: Request) -> Any:
    graph = request.app.state.graph
    async with request.app.state.pool.connection() as conn:
        counts = await queries.graph_status(conn, EXTRACTOR_VERSION)
    return {**counts, "model": graph.model, "available": graph.available}


@router.post(
    "/graph/extract",
    operation_id="graphExtract",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ExtractQueued,
    dependencies=[Depends(require_same_origin)],
    responses={**ERRORS, 409: {"model": ErrorResponse}},
)
async def graph_extract(body: GraphExtractRequest, request: Request) -> ExtractQueued:
    if not request.app.state.graph.available:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="extraction_unavailable")
    queue = await request.app.state.ingest.get_queue()
    if queue is None:  # the job app can't open: the database is down
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="database_unavailable")
    try:
        async with request.app.state.pool.connection() as conn:
            queued = await queries.queue_extraction(conn, queue, EXTRACTOR_VERSION, body.scope)
    except Exception as error:  # a deferral failed; the next run re-queues what was lost
        logger.warning("graph_extract_queue_error type=%s", type(error).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="database_unavailable"
        ) from error
    return ExtractQueued(queued=queued)


@router.get(
    "/review/entities",
    operation_id="reviewEntities",
    response_model=ReviewEntityPage,
    responses=ERRORS,
)
async def review_entities(
    request: Request, type: EntityType | None = None, cursor: Cursor = None
) -> Any:
    settings = get_settings(request)
    try:
        async with request.app.state.pool.connection() as conn:
            return await queries.review_entities(
                conn,
                type=type,
                cursor=cursor,
                space_id=request.app.state.ingest.space_id,
                min_similarity=settings.entity_match_similarity,
                vault_name=settings.obsidian_vault_name,
            )
    except InvalidCursorError as error:
        raise _invalid_cursor() from error


async def _apply(conn: AsyncConnection, entity_id: UUID, body: EntityDecision) -> UUID:
    """Run the decision; returns the id of the entity to show afterwards."""
    match body.action:
        case "accept":
            await decide.accept_entity(conn, entity_id)
        case "reject":
            await decide.reject_entity(conn, entity_id)
        case "rename" if body.name is not None:
            await decide.rename_entity(conn, entity_id, body.name)
        case "retype" if body.type is not None:
            await decide.retype_entity(conn, entity_id, body.type)
        case "parent":
            await decide.set_parent(conn, entity_id, body.parent_id)
        case "merge" if body.into_id is not None:
            return await decide.merge_entities(conn, entity_id, body.into_id)
        case _:
            raise decide.DecisionError("invalid_action")
    return entity_id


async def _in_transaction[T](
    request: Request, action: Callable[[AsyncConnection], Awaitable[T]]
) -> T:
    """Run one decision in one transaction; a deadlock or serialization loser retries once."""
    pool = request.app.state.pool
    for attempt in (1, 2):
        try:
            async with pool.connection() as conn, conn.transaction():
                return await action(conn)
        except (DeadlockDetected, SerializationFailure) as error:
            logger.info("decide_conflict attempt=%d type=%s", attempt, type(error).__name__)
            if attempt == 2:
                raise HTTPException(status.HTTP_409_CONFLICT, detail="busy") from error
        except decide.DecisionError as error:
            raise HTTPException(DECISION_STATUS[error.code], detail=error.code) from error
    raise AssertionError("unreachable")


@router.post(
    "/entities/{entity_id}/decide",
    operation_id="decideEntity",
    response_model=EntityDecided,
    dependencies=[Depends(require_same_origin)],
    responses={**ERRORS, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def decide_entity(entity_id: UUID, body: EntityDecision, request: Request) -> Any:
    shown = await _in_transaction(request, lambda conn: _apply(conn, entity_id, body))
    pool = request.app.state.pool
    space_id = request.app.state.ingest.space_id
    if body.action == "merge":
        async with pool.connection() as conn:
            missing = await graph_store.missing_embedding(conn, shown, space_id)
        if missing:
            queue = await request.app.state.ingest.get_queue()
            try:
                if queue is None:
                    raise RuntimeError("queue unavailable")
                await queue.embed_entity(shown)
            except Exception as error:  # the merge stands; the embedding can come later
                logger.warning(
                    "decide_embed_queue_error entity=%s type=%s", shown, type(error).__name__
                )
    async with pool.connection() as conn:
        entity = await queries.get_entity(conn, shown, vault_name=_vault_name(request))
    if entity is None:  # deleted by a concurrent merge right after this decision
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
    return {"entity": entity}


@router.get(
    "/review/links", operation_id="reviewLinks", response_model=ReviewLinkPage, responses=ERRORS
)
async def review_links(request: Request, cursor: Cursor = None) -> Any:
    try:
        async with request.app.state.pool.connection() as conn:
            return await queries.review_links(conn, cursor=cursor, vault_name=_vault_name(request))
    except InvalidCursorError as error:
        raise _invalid_cursor() from error


@router.post(
    "/review/links",
    operation_id="decideLinks",
    response_model=LinksUpdated,
    dependencies=[Depends(require_same_origin)],
    responses={**ERRORS, 409: {"model": ErrorResponse}},
)
async def decide_links(body: LinkDecisions, request: Request) -> LinksUpdated:
    items: list[tuple[UUID, Literal["accept", "reject"]]] = [
        (item.id, item.decision) for item in body.items
    ]
    updated = await _in_transaction(request, lambda conn: decide.decide_links(conn, items))
    return LinksUpdated(updated=updated)


@router.get("/entities", operation_id="listEntities", response_model=EntityPage, responses=ERRORS)
async def list_entities(
    request: Request,
    type: EntityType | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: Cursor = None,
) -> Any:
    if q is not None and "\x00" in q:
        raise HTTPException(422, detail="invalid_query")
    try:
        async with request.app.state.pool.connection() as conn:
            return await queries.list_entities(conn, type=type, q=q or None, cursor=cursor)
    except InvalidCursorError as error:
        raise _invalid_cursor() from error


@router.get(
    "/entities/{entity_id}",
    operation_id="getEntity",
    response_model=EntityDetail,
    responses={**ERRORS, 404: {"model": ErrorResponse}},
)
async def get_entity(entity_id: UUID, request: Request) -> Any:
    async with request.app.state.pool.connection() as conn:
        entity = await queries.get_entity(conn, entity_id, vault_name=_vault_name(request))
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not_found")
    return entity
