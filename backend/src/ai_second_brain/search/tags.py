"""Frontmatter tags → a clean list. The SQL backfill in the 2b migration mirrors this exactly."""

import re

_SPLIT = re.compile(r"[,\s]+")
_WS = " \t\n\r"
MAX_TAGS, MAX_TAG_CHARS = 64, 100


def normalise_tags(value: object) -> list[str]:
    if isinstance(value, str):
        items = _SPLIT.split(value)
    elif isinstance(value, list):
        items = [item for item in value if isinstance(item, str)]
    else:
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = item.strip(_WS).lstrip("#").strip(_WS).lower()
        if not tag or len(tag) > MAX_TAG_CHARS or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) == MAX_TAGS:
            break
    return tags
