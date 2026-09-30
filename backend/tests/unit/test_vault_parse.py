import json

from ai_second_brain.vault.parse import ParsedNote, parse_note


def test_title_prefers_frontmatter_then_h1_then_stem() -> None:
    assert parse_note("---\ntitle: From FM\n---\n# H1\nbody", "file").title == "From FM"
    assert parse_note("intro\n# The H1 #\nbody", "file").title == "The H1"
    assert parse_note("```\n# not a title\n```\ntext", "file").title == "file"
    assert parse_note("---\ntitle: '  '\n---\nx", "stem").title == "stem"


def test_frontmatter_is_json_safe_and_removed_from_body() -> None:
    parsed = parse_note("---\ntags: [a, b]\ndate: 2026-09-30\n---\nBody here", "f")
    assert parsed.frontmatter == {"tags": ["a", "b"], "date": "2026-09-30"}
    assert parsed.frontmatter_error is False
    assert parsed.body == "Body here"


def test_invalid_or_non_dict_frontmatter_stays_in_body() -> None:
    broken = parse_note("---\nkey: [unclosed\n---\nBody", "f")
    assert broken.frontmatter is None and broken.frontmatter_error is True
    assert broken.body.startswith("---\nkey: [unclosed")
    listy = parse_note("---\n- a\n- b\n---\nBody", "f")
    assert listy.frontmatter is None and listy.frontmatter_error is True


def test_wikilinks_outside_code_deduplicated() -> None:
    text = (
        "See [[NAS]] and [[Backups|the backups]] and [[NAS#Disks]].\n"
        "`[[inline code]]`\n"
        "```\n[[in fence]]\n```\n"
    )
    assert parse_note(text, "f").links == ["NAS", "Backups"]


def _round_trips(parsed: ParsedNote) -> None:
    json.dumps(parsed.frontmatter, allow_nan=False)


def test_date_key_is_stringified() -> None:
    parsed = parse_note("---\n2026-09-30: daily\n---\nBody", "f")
    assert parsed.frontmatter == {"2026-09-30": "daily"}
    _round_trips(parsed)


def test_non_finite_floats_become_strings() -> None:
    parsed = parse_note("---\na: .nan\nb: .inf\nc: -.inf\n---\nBody", "f")
    assert parsed.frontmatter == {"a": "nan", "b": "inf", "c": "-inf"}
    _round_trips(parsed)


def test_recursive_anchor_is_invalid_frontmatter() -> None:
    parsed = parse_note("---\na: &a [*a]\n---\nBody", "f")
    assert parsed.frontmatter is None and parsed.frontmatter_error is True
    assert parsed.body.startswith("---\na: &a")


def test_nul_in_string_value_is_removed() -> None:
    parsed = parse_note('---\nk: "a\\0b"\n---\nBody', "f")
    assert parsed.frontmatter == {"k": "ab"}
    _round_trips(parsed)
