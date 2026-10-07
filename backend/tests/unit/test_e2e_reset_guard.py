import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "e2e_reset", Path(__file__).resolve().parents[1] / "e2e_reset.py"
)
assert _spec and _spec.loader
e2e_reset = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e2e_reset)

DEV = "postgres://brain:brain@127.0.0.1:5433/ai_second_brain?sslmode=disable"
TEST = "postgres://brain:brain@127.0.0.1:5433/ai_second_brain_test?sslmode=disable"


def test_test_database_accepted() -> None:
    assert e2e_reset.is_test_database(TEST)


@pytest.mark.parametrize(
    "url",
    [DEV, "", "postgres://u:p_test@host_test:5433/ai_second_brain", "postgres://h/x_test/y"],
)
def test_other_databases_refused(url: str) -> None:
    assert not e2e_reset.is_test_database(url)


def test_guarded_url_exits_without_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DEV)
    with pytest.raises(SystemExit) as exc:
        e2e_reset.guarded_url()
    assert exc.value.code != 0
