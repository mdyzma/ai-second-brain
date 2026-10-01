"""The real chat Retriever: hybrid query in chat mode, similarity floor, evidence budget."""

import logging
import time
from typing import Any

from psycopg_pool import AsyncConnectionPool

from ai_second_brain.chat.models import Source
from ai_second_brain.chat.retrieval import Retrieval, RetrievalMode
from ai_second_brain.config import Settings
from ai_second_brain.search.embedding import QueryEmbedder
from ai_second_brain.search.evidence import select_evidence
from ai_second_brain.search.links import obsidian_url
from ai_second_brain.search.query import query
from ai_second_brain.search.terms import chat_terms

logger = logging.getLogger("ai_second_brain.search")

# Chat already waits for an LLM; a cold embedding model must not throw away retrieval.
CHAT_EMBED_TIMEOUT = 8.0


class HybridRetriever:
    def __init__(
        self, pool: AsyncConnectionPool[Any], embedder: QueryEmbedder, settings: Settings
    ) -> None:
        self._pool, self._embedder, self._settings = pool, embedder, settings

    async def retrieve(self, question: str, limit: int) -> Retrieval:
        started = time.perf_counter()
        vector = await self._embedder.embed(question, timeout=CHAT_EMBED_TIMEOUT)
        terms = chat_terms(question)
        async with self._pool.connection() as conn:
            result = await query(
                conn, question, vector=vector, mode="chat", terms=terms, limit=limit * 2
            )
        floor = self._settings.retrieval_min_similarity
        relevant = [
            hit
            for hit in result.hits
            if "text" in hit.matched or (hit.similarity is not None and hit.similarity >= floor)
        ]
        vault = self._settings.obsidian_vault_name
        sources = [
            Source(
                n=i,
                source_id=str(hit.source_id),
                path=hit.path,
                heading=" › ".join(hit.heading_path) or None,
                score=hit.score,
                snippet=hit.content,
                obsidian_url=obsidian_url(vault, hit.path),
            )
            for i, hit in enumerate(select_evidence(relevant, limit=limit), start=1)
        ]
        mode: RetrievalMode = "hybrid" if vector is not None else "text_only"
        logger.info(
            "retrieve q_len=%d sources=%d mode=%s ms=%d",
            len(question),
            len(sources),
            mode,
            (time.perf_counter() - started) * 1000,
        )
        return Retrieval(sources, mode)
