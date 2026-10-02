from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ai_second_brain.config import REPO_ROOT, Settings
from ai_second_brain.eval.guards import check_eval_url, same_database
from ai_second_brain.eval.queries import EvalConfigError

from ..conftest import TEST_HASH

DEV = "postgres://brain:brain@127.0.0.1:5433/ai_second_brain?sslmode=disable"
TEST = "postgres://brain:brain@127.0.0.1:5433/ai_second_brain_test?sslmode=disable"


def make(**values: Any) -> Settings:
    base: dict[str, Any] = {"DATABASE_URL": DEV, "owner_password_hash": TEST_HASH}
    return Settings(_env_file=None, **(base | values))  # pyright: ignore[reportCallIssue]


def test_eval_url_default_suffixes_database_name() -> None:
    assert make().eval_database_url == (
        "postgres://brain:brain@127.0.0.1:5433/ai_second_brain_eval?sslmode=disable"
    )


def test_eval_url_override() -> None:
    url = "postgres://u:p@h:5432/other"
    assert make(SB_EVAL_DATABASE_URL=url).eval_database_url == url


def test_eval_model_list_replaces_incumbent_with_embed_tag() -> None:
    assert make(embed_model="bge-m3:567m").eval_model_list == [
        "bge-m3:567m",
        "snowflake-arctic-embed2",
        "granite-embedding:278m",
        "paraphrase-multilingual",
    ]


def test_cloud_model_refused() -> None:
    with pytest.raises(ValidationError):
        make(eval_models="bge-m3,gpt-oss:120b-cloud")


def test_eval_dir_inside_repo_refused() -> None:
    with pytest.raises(ValidationError):
        make(eval_dir=str(REPO_ROOT / "reports"))


def test_paths_expand_user() -> None:
    settings = make()
    assert settings.eval_queries_path == Path("~/.second-brain/eval/queries.yaml").expanduser()
    assert settings.eval_report_dir == Path("~/.second-brain/eval/reports").expanduser()


def test_same_database_normalises() -> None:
    assert same_database(DEV, "postgres://x:y@localhost:5433/ai_second_brain")
    assert same_database("postgres://a@h/db", "postgres://a@h:5432/db")
    assert not same_database(DEV, TEST)


def test_eval_url_equal_to_dev_after_normalising_is_refused() -> None:
    with pytest.raises(EvalConfigError):
        check_eval_url("postgres://brain:brain@localhost:5433/ai_second_brain", DEV, TEST)
    with pytest.raises(EvalConfigError):
        check_eval_url(TEST, DEV, TEST)
    check_eval_url(make().eval_database_url, DEV, TEST)  # no raise
