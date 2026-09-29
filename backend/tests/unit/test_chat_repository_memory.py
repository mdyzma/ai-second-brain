from datetime import datetime, timedelta

from ai_second_brain.chat.repository import InMemoryChatRepository

from ..conftest import run_async
from ..repository_contract import BASE, RepositoryContract, Scenario


class Tick:
    """Clock that advances one second per call, so creation order is observable."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return BASE + timedelta(seconds=self.calls)


class TestInMemoryChatRepository(RepositoryContract):
    def run(self, scenario: Scenario) -> None:
        run_async(scenario(InMemoryChatRepository(clock=Tick())))
