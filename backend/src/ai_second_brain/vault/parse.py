"""Obsidian note parsing: frontmatter, title, wikilinks. Pure and total."""

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

import yaml

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
H1 = re.compile(r"^#[ \t]+(.+?)[ \t#]*$")
INLINE_CODE = re.compile(r"`[^`\n]*`")
WIKILINK = re.compile(r"\[\[([^\]\|#\n]+)(?:#[^\]\|\n]*)?(?:\|[^\]\n]*)?\]\]")


@dataclass(frozen=True)
class ParsedNote:
    title: str
    body: str
    frontmatter: dict[str, Any] | None
    frontmatter_error: bool
    links: list[str] = field(default_factory=list)


def iter_outside_code(lines: Iterable[str]) -> Iterator[tuple[str, bool]]:
    """Yield (line, in_code). Fence open/close lines count as in_code."""
    fence: str | None = None
    for line in lines:
        match = FENCE.match(line)
        if fence is None and match:
            fence = match.group(1)[0] * len(match.group(1))
            yield line, True
        elif fence is not None:
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
                fence = None
            yield line, True
        else:
            yield line, False


def _frontmatter(text: str) -> tuple[dict[str, Any] | None, bool, str]:
    match = FRONTMATTER.match(text)
    if not match:
        return None, False, text
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None, True, text
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        return None, True, text
    safe = json.loads(json.dumps(loaded, default=str))
    return safe, False, text[match.end() :]


def parse_note(text: str, stem: str) -> ParsedNote:
    frontmatter, error, body = _frontmatter(text)
    title = None
    if frontmatter and isinstance(frontmatter.get("title"), str) and frontmatter["title"].strip():
        title = frontmatter["title"].strip()
    links: list[str] = []
    for line, in_code in iter_outside_code(body.split("\n")):
        if in_code:
            continue
        if title is None and (h1 := H1.match(line)):
            title = h1.group(1).strip()
        for target in WIKILINK.findall(INLINE_CODE.sub("", line)):
            target = target.strip()
            if target and target not in links:
                links.append(target)
    return ParsedNote(title or stem, body, frontmatter, error, links)
