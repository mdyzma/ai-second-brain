"""Question → OR-able search terms for chat retrieval. Terms never contain tsquery syntax."""

import re
from dataclasses import dataclass

_TOKEN = re.compile(r"\w(?:[\w.\-]*\w)?")
MAX_TERMS = 16


@dataclass(frozen=True)
class ChatTerms:
    terms: tuple[str, ...]
    identifiers: tuple[str, ...]


def _is_identifier(token: str) -> bool:
    return 2 <= len(token) <= 64 and any(ch.isdigit() or ch in "._-" for ch in token)


def chat_terms(question: str) -> ChatTerms:
    identifiers: list[str] = []
    words: list[str] = []
    for token in _TOKEN.findall(question.lower()):
        bucket = identifiers if _is_identifier(token) else words
        if (_is_identifier(token) or len(token) >= 3) and token not in bucket:
            bucket.append(token)
    words.sort(key=len, reverse=True)
    chosen = (identifiers + words)[:MAX_TERMS]
    return ChatTerms(tuple(chosen), tuple(t for t in identifiers if t in chosen))
