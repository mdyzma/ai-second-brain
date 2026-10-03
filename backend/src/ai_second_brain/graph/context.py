from dataclasses import dataclass

from psycopg_pool import AsyncConnectionPool

from ai_second_brain.config import Settings
from ai_second_brain.graph.llm import ExtractClient
from ai_second_brain.knowledge.queue import JobQueue
from ai_second_brain.search.embedding import QueryEmbedder


@dataclass(frozen=True)
class GraphContext:
    pool: AsyncConnectionPool
    settings: Settings
    client: ExtractClient | None
    names: QueryEmbedder | None
    queue: JobQueue
