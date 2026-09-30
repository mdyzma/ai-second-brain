"""Heading-aware chunking. Chunks are ≤ MAX_CHARS; continuation chunks start with overlap."""

import re
from dataclasses import dataclass

from ai_second_brain.vault.parse import iter_outside_code

MAX_CHARS = 1600
OVERLAP = 200
UNIT_MAX = MAX_CHARS - OVERLAP - 2  # a unit always fits after an overlap + "\n\n"

HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    heading_path: tuple[str, ...]
    content: str


def _sections(body: str) -> list[tuple[tuple[str, ...], str]]:
    sections: list[tuple[tuple[str, ...], list[str]]] = [((), [])]
    stack: list[tuple[int, str]] = []
    for line, in_code in iter_outside_code(body.split("\n")):
        match = None if in_code else HEADING.match(line)
        if match:
            level = len(match.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, match.group(2).strip()))
            sections.append((tuple(text for _, text in stack), []))
        else:
            sections[-1][1].append(line)
    return [(path, "\n".join(lines).strip()) for path, lines in sections]


def _units(text: str) -> list[tuple[str, str]]:
    """(joiner, unit) pairs; joiner is used before the unit inside a chunk."""
    units: list[tuple[str, str]] = []
    for paragraph in (p.strip() for p in PARAGRAPH_BREAK.split(text)):
        if not paragraph:
            continue
        if len(paragraph) <= UNIT_MAX:
            units.append(("\n\n", paragraph))
            continue
        first = True
        for sentence in (s for s in SENTENCE_END.split(paragraph) if s):
            for start in range(0, len(sentence), UNIT_MAX):
                # Hard-split pieces of one sentence rejoin with "" so tokens stay intact.
                joiner = ("\n\n" if first else " ") if start == 0 else ""
                units.append((joiner, sentence[start : start + UNIT_MAX]))
                first = False
    return units


def _overlap(previous: str) -> str:
    if len(previous) <= OVERLAP:
        return previous.strip()
    tail = previous[-OVERLAP:]
    space = next((i for i, ch in enumerate(tail) if ch.isspace()), -1)
    snapped = tail[space + 1 :].lstrip() if space != -1 else tail
    return snapped or tail.strip()


def _split(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    chunks: list[str] = []
    current = ""
    for joiner, unit in _units(text):
        if not current:
            current = unit
        elif len(current) + len(joiner) + len(unit) <= MAX_CHARS:
            current = f"{current}{joiner}{unit}"
        else:
            chunks.append(current)
            current = f"{_overlap(current)}\n\n{unit}"
    if current:
        chunks.append(current)
    return chunks


def chunk_note(body: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path, text in _sections(body):
        if not text:
            continue
        for content in _split(text):
            chunks.append(Chunk(len(chunks), path, content))
    return chunks
