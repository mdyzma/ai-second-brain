"""Split a note into model-sized windows on chunk boundaries; merge per-window outputs."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from ai_second_brain.graph.names import norm
from ai_second_brain.graph.schema import (
    MAX_ALIASES,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionOutput,
)

MAX_ENTITIES = 30
MAX_RELATIONS = 50
_TAIL = "\n\n"


@dataclass(frozen=True)
class Window:
    text: str
    labels: dict[str, UUID] = field(default_factory=dict)  # "c1" -> chunk id


def _head(label: str, heading: str) -> str:
    return f"[{label}] {heading}\n" if heading else f"[{label}]\n"


def split_windows(chunks: Sequence[tuple[UUID, str, str]], *, max_chars: int) -> list[Window]:
    """Pack chunks into windows of at most `max_chars`; labels restart at c1 per window.

    A chunk that does not fit the room left starts a new window. One longer than a whole
    window is cut by characters; every piece keeps the chunk's label for its window.
    """
    windows: list[Window] = []
    text = ""
    labels: dict[str, UUID] = {}

    def flush() -> None:
        nonlocal text, labels
        if text:
            windows.append(Window(text.rstrip(), labels))
        text, labels = "", {}

    for chunk_id, heading, content in chunks:
        rest = content
        while True:
            head = _head(f"c{len(labels) + 1}", heading)
            if text and len(text) + len(head) + len(rest) + len(_TAIL) > max_chars:
                flush()
                head = _head("c1", heading)
            room = max(max_chars - len(text) - len(head) - len(_TAIL), 1)
            piece, rest = rest[:room], rest[room:]
            labels[f"c{len(labels) + 1}"] = chunk_id
            text += head + piece + _TAIL
            if not rest:
                break
            flush()
    flush()
    return windows


def merge_outputs(outputs: Sequence[ExtractionOutput]) -> ExtractionOutput:
    if not outputs:
        return ExtractionOutput(summary="", entities=[], relations=[])
    entities: dict[tuple[str, str], ExtractedEntity] = {}
    relations: dict[tuple[str, str, str], ExtractedRelation] = {}
    for out in outputs:
        for e in out.entities:
            key = (e.type, norm(e.name))
            kept = entities.get(key)
            if kept is None:
                entities[key] = e.model_copy()
                continue
            aliases = list(dict.fromkeys([*kept.aliases, *e.aliases]))[:MAX_ALIASES]
            entities[key] = kept.model_copy(
                update={"confidence": max(kept.confidence, e.confidence), "aliases": aliases}
            )
        for r in out.relations:
            rkey = (norm(r.subject), r.relation, norm(r.object))
            rkept = relations.get(rkey)
            if rkept is None:
                relations[rkey] = r.model_copy()
            elif r.confidence > rkept.confidence:
                relations[rkey] = rkept.model_copy(update={"confidence": r.confidence})
    return ExtractionOutput(
        summary=outputs[0].summary,
        entities=list(entities.values())[:MAX_ENTITIES],
        relations=list(relations.values())[:MAX_RELATIONS],
    )
