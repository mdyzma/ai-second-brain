"""Never let the scratch database be the dev or test database."""

from urllib.parse import urlsplit

from ai_second_brain.eval.queries import EvalConfigError


def _key(url: str) -> tuple[str, int, str]:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    host = "127.0.0.1" if host in ("localhost", "::1") else host
    return host, parts.port or 5432, parts.path.lstrip("/")


def same_database(a: str, b: str) -> bool:
    return _key(a) == _key(b)


def check_eval_url(eval_url: str, dev_url: str, test_url: str | None) -> None:
    if same_database(eval_url, dev_url) or (test_url and same_database(eval_url, test_url)):
        raise EvalConfigError(["SB_EVAL_DATABASE_URL must not be the dev or test database"])
