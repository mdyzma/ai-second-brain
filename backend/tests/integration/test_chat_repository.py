import pytest

from ai_second_brain.chat.repository import PgChatRepository
from ai_second_brain.db import create_pool

from ..conftest import run_async
from ..repository_contract import RepositoryContract, Scenario

pytestmark = pytest.mark.integration


class TestPgChatRepository(RepositoryContract):
    @pytest.fixture(autouse=True)
    def _url(self, db_url: str) -> None:
        self.url = db_url

    def run(self, scenario: Scenario) -> None:
        async def with_pool() -> None:
            async with create_pool(self.url) as pool:
                async with pool.connection() as conn:
                    await conn.execute("TRUNCATE chat_sessions CASCADE")
                await scenario(PgChatRepository(pool))

        run_async(with_pool())
