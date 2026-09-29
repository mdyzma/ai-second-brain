"""PostgreSQL connection pool (psycopg 3, async)."""

import psycopg
from psycopg_pool import AsyncConnectionPool, PoolTimeout


def create_pool(database_url: str) -> AsyncConnectionPool:
    """Pool opened by the app lifespan. Connections are established in the background."""
    return AsyncConnectionPool(
        conninfo=database_url,
        min_size=1,
        max_size=5,
        open=False,
        timeout=3.0,
        kwargs={"connect_timeout": 3},
    )


async def ping(pool: AsyncConnectionPool, timeout: float = 2.0) -> bool:  # noqa: ASYNC109
    try:
        async with pool.connection(timeout=timeout) as conn:
            await conn.execute("SELECT 1")
    except (PoolTimeout, psycopg.Error, OSError):
        return False
    return True
