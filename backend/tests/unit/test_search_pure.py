import pytest

from ai_second_brain.search.links import obsidian_url
from ai_second_brain.search.tags import normalise_tags
from ai_second_brain.search.terms import chat_terms

TAG_CASES: list[tuple[object, list[str]]] = [
    (None, []),
    (42, []),
    ({"a": 1}, []),
    ("", []),
    ("homelab", ["homelab"]),
    ("#a, b c", ["a", "b", "c"]),
    ("A,a,#A", ["a"]),
    (["Proj", "#proj", "  x  ", 3, None, ""], ["proj", "x"]),
    (["two words"], ["two words"]),
    (["Zażółć"], ["zażółć"]),
    (["x" * 101, "ok"], ["ok"]),
    ([f"t{i}" for i in range(70)], [f"t{i}" for i in range(64)]),
]


@pytest.mark.parametrize(("value", "expected"), TAG_CASES)
def test_normalise_tags(value: object, expected: list[str]) -> None:
    assert normalise_tags(value) == expected


def test_obsidian_url_encodes_vault_and_file() -> None:
    url = obsidian_url("My Vault", "Projects/NAS #1 & co/Zażółć.md")
    assert url == (
        "obsidian://open?vault=My%20Vault"
        "&file=Projects%2FNAS%20%231%20%26%20co%2FZa%C5%BC%C3%B3%C5%82%C4%87.md"
    )
    assert obsidian_url("", "a.md") is None


def test_chat_terms_identifiers_and_words() -> None:
    terms = chat_terms("What's the IP of nas01? Is 192.168.1.10 or ERR_TIMEOUT in v1.2 ok?")
    assert set(terms.identifiers) == {"nas01", "192.168.1.10", "err_timeout", "v1.2"}
    assert "what" in terms.terms and "the" in terms.terms and "of" not in terms.terms
    assert "ok" not in terms.terms  # words need 3+ characters


def test_chat_terms_cap_prefers_identifiers_then_longest() -> None:
    words = " ".join(f"word{'x' * i}" for i in range(20))
    terms = chat_terms(f"{words} host01")
    assert len(terms.terms) == 16
    assert "host01" in terms.terms
    assert "word" not in terms.terms  # shortest words dropped first


def test_chat_terms_strip_tsquery_operators() -> None:
    terms = chat_terms("a & b | !c :* 'quoted' (paren) <-> \"x\"")
    for term in terms.terms:
        assert all(ch.isalnum() or ch in "._-" for ch in term)


def test_chat_terms_empty() -> None:
    assert chat_terms("?? !! a").terms == ()
