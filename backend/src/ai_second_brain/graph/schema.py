"""Extraction output: lenient filter (drop, never repair), then strict validation."""

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_second_brain.graph.names import norm

ENTITY_TYPES = ("project", "person", "organization", "tool", "device", "topic")
RELATIONS = ("mentions", "about", "uses", "runs_on", "works_with", "part_of")
EntityType = Literal["project", "person", "organization", "tool", "device", "topic"]
Relation = Literal["mentions", "about", "uses", "runs_on", "works_with", "part_of"]
MAX_ENTITIES, MAX_RELATIONS, MAX_ALIASES, MAX_NAME, MAX_SUMMARY = 30, 50, 5, 200, 200


class InvalidOutput(Exception):  # noqa: N818 - name is the cross-task contract
    pass


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=MAX_NAME)
    type: EntityType
    aliases: list[str] = Field(default_factory=list, max_length=MAX_ALIASES)
    confidence: float = Field(ge=0, le=1)


class ExtractedRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=MAX_NAME)
    relation: Relation
    object: str = Field(min_length=1, max_length=MAX_NAME)
    chunk: str | None = None
    confidence: float = Field(ge=0, le=1)


class ExtractionOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=MAX_SUMMARY)
    entities: list[ExtractedEntity] = Field(max_length=MAX_ENTITIES)
    relations: list[ExtractedRelation] = Field(max_length=MAX_RELATIONS)


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            return _inline_refs(defs[ref.rsplit("/", 1)[-1]], defs)
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


def output_json_schema() -> dict[str, Any]:
    """Schema with every definition inlined (grammar-based decoders may not follow $ref)."""
    schema = ExtractionOutput.model_json_schema()
    return _inline_refs(schema, schema.get("$defs", {}))


def _clamp(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    try:
        number = float(value)
    except OverflowError:
        return 0.0
    return min(1.0, max(0.0, number)) if math.isfinite(number) else 0.0


def _clean(value: object) -> str:
    return " ".join(value.split())[:MAX_NAME] if isinstance(value, str) else ""


_CHUNK = re.compile(r"c\d{1,4}")


def _aliases(value: object, name_key: str) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen = {name_key}
    for item in value:
        alias = _clean(item)
        key = norm(alias)
        if key and key not in seen:
            seen.add(key)
            out.append(alias)
        if len(out) == MAX_ALIASES:
            break
    return out


def filter_output(raw: object) -> ExtractionOutput:
    if not isinstance(raw, dict):
        raise InvalidOutput("not an object")
    summary, ents, rels = raw.get("summary", ""), raw.get("entities", []), raw.get("relations", [])
    if not isinstance(summary, str) or not isinstance(ents, list) or not isinstance(rels, list):
        raise InvalidOutput("wrong field types")
    entities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ents:
        if not isinstance(item, dict) or item.get("type") not in ENTITY_TYPES:
            continue
        name = _clean(item.get("name"))
        key = norm(name)
        if not key or key == "note" or key in seen:
            continue
        seen.add(key)
        entities.append(
            {
                "name": name,
                "type": item["type"],
                "aliases": _aliases(item.get("aliases"), key),
                "confidence": _clamp(item.get("confidence")),
            }
        )
        if len(entities) == MAX_ENTITIES:
            break
    relations: list[dict[str, Any]] = []
    rel_seen: set[tuple[str, str, str]] = set()
    for item in rels:
        if not isinstance(item, dict) or item.get("relation") not in RELATIONS:
            continue
        subject, obj = _clean(item.get("subject")), _clean(item.get("object"))
        subject_key, obj_key = norm(subject), norm(obj)
        if (subject != "NOTE" and subject_key not in seen) or obj_key not in seen:
            continue
        if subject_key == obj_key or (subject_key, item["relation"], obj_key) in rel_seen:
            continue
        rel_seen.add((subject_key, item["relation"], obj_key))
        chunk = item.get("chunk")
        relations.append(
            {
                "subject": subject,
                "relation": item["relation"],
                "object": obj,
                "chunk": chunk if isinstance(chunk, str) and _CHUNK.fullmatch(chunk) else None,
                "confidence": _clamp(item.get("confidence")),
            }
        )
        if len(relations) == MAX_RELATIONS:
            break
    try:
        return ExtractionOutput.model_validate(
            {
                "summary": " ".join(summary.split())[:MAX_SUMMARY],
                "entities": entities,
                "relations": relations,
            }
        )
    except ValidationError:
        raise InvalidOutput("schema validation failed") from None
