from dataclasses import dataclass

from psycopg_pool import AsyncConnectionPool

from ai_second_brain.config import Settings
from ai_second_brain.knowledge.embedder import Embedder
from ai_second_brain.knowledge.queue import JobQueue
from ai_second_brain.vault.paths import Vault


@dataclass(frozen=True)
class IngestContext:
    pool: AsyncConnectionPool
    settings: Settings
    vault: Vault | None
    embedder: Embedder | None
    queue: JobQueue
    space_id: int
    space_model: str
    space_dims: int
