from urllib.parse import parse_qs, urlsplit

import pytest

from ..eval_db import _with_db, eval_db_name


def test_with_db_drops_a_dbname_query_parameter() -> None:
    url = _with_db("postgres://u:p@127.0.0.1:5432/brain_test?dbname=brain&sslmode=disable", "x")
    parts = urlsplit(url)
    assert parts.path == "/x"
    assert parse_qs(parts.query) == {"sslmode": ["disable"]}


def test_eval_db_name_is_the_test_name_with_suffix() -> None:
    assert eval_db_name("postgres://u@127.0.0.1/brain_test?dbname=brain") == "brain_test_eval"


def test_eval_db_name_needs_a_path_database() -> None:
    with pytest.raises(RuntimeError):
        eval_db_name("postgres://u@127.0.0.1/?dbname=brain")
