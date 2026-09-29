import pytest

from ai_second_brain.interfaces.api.deps import is_same_origin

ALLOWED = frozenset({"http://localhost:5173"})


@pytest.mark.parametrize(
    ("method", "fetch_site", "origin", "expected"),
    [
        ("GET", None, None, True),  # safe methods are never checked
        ("HEAD", "cross-site", "http://evil.example", True),
        ("POST", "same-origin", None, True),
        ("POST", None, "http://localhost:5173", True),
        ("POST", None, "http://localhost:5173/", True),  # trailing slash tolerated
        ("POST", "cross-site", "http://localhost:5173", True),  # allowed origin wins
        ("POST", "cross-site", "http://evil.example", False),
        ("POST", None, "http://evil.example", False),
        ("POST", None, None, False),  # non-browser clients are rejected
        ("DELETE", "same-site", None, False),
        ("PATCH", None, "null", False),
    ],
)
def test_is_same_origin(
    method: str, fetch_site: str | None, origin: str | None, expected: bool
) -> None:
    assert is_same_origin(method, fetch_site, origin, ALLOWED) is expected
