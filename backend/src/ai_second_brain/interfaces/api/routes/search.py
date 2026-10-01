import logging
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ai_second_brain.interfaces.api.deps import get_settings, require_session
from ai_second_brain.interfaces.api.schemas import (
    ErrorResponse,
    FolderFacet,
    SearchFacets,
    SearchHit,
    SearchResponse,
    TagFacet,
)
from ai_second_brain.search.embedding import excerpt
from ai_second_brain.search.facets import facets
from ai_second_brain.search.links import obsidian_url
from ai_second_brain.search.query import query
from ai_second_brain.search.tags import normalise_tags

logger = logging.getLogger("ai_second_brain.search")
router = APIRouter(tags=["search"], dependencies=[Depends(require_session)])
ERRORS: dict[int | str, dict[str, Any]] = {
    k: {"model": ErrorResponse} for k in (401, 409, 422, 503)
}


def _require_vault(request: Request) -> None:
    if get_settings(request).vault_path is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="vault_disabled")


@router.get("/search", operation_id="searchNotes", response_model=SearchResponse, responses=ERRORS)
async def search_notes(
    request: Request,
    q: Annotated[str, Query(max_length=500)],
    folder: Annotated[str | None, Query(max_length=500)] = None,
    tag: Annotated[list[str] | None, Query(max_length=10)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchResponse:
    _require_vault(request)
    text = q.strip()
    if not text or "\x00" in q or (folder and "\x00" in folder):
        raise HTTPException(422, detail="invalid_query")
    settings = get_settings(request)
    started = time.perf_counter()
    vector = await request.app.state.query_embedder.embed(text)
    tags = normalise_tags(tag or [])
    async with request.app.state.pool.connection() as conn:
        result = await query(
            conn,
            text,
            vector=vector,
            folder=(folder or "").strip("/") or None,
            tags=tags,
            limit=limit,
        )
    vault_name = settings.obsidian_vault_name
    hits = [
        SearchHit(
            source_id=hit.source_id,
            path=hit.path,
            title=hit.title,
            heading_path=list(hit.heading_path),
            snippet=hit.headline or excerpt(hit.content),
            matched=sorted(hit.matched),  # type: ignore[arg-type]
            score=hit.score,
            obsidian_url=obsidian_url(vault_name, hit.path),
        )
        for hit in result.hits
    ]
    state = "ok" if result.vector_used else "unavailable"
    logger.info(
        "search q_len=%d filters=%d results=%d vector=%s ms=%d",
        len(text),
        int(bool(folder)) + len(tags),
        len(hits),
        state,
        (time.perf_counter() - started) * 1000,
    )
    return SearchResponse(vector=state, results=hits)


@router.get(
    "/search/facets", operation_id="searchFacets", response_model=SearchFacets, responses=ERRORS
)
async def search_facets(request: Request) -> SearchFacets:
    _require_vault(request)
    async with request.app.state.pool.connection() as conn:
        folders, tags = await facets(conn)
    return SearchFacets(
        folders=[FolderFacet(path=p, count=n) for p, n in folders],
        tags=[TagFacet(tag=t, count=n) for t, n in tags],
    )
