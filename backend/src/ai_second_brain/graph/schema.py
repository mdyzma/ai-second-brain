"""Extraction output: lenient filter (drop, never repair), then strict validation."""

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


def output_json_schema() -> dict[str, Any]:
    return ExtractionOutput.model_json_schema()


def _clamp(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, number))


def _clean(value: object) -> str:
    return " ".join(value.split())[:MAX_NAME] if isinstance(value, str) else ""


def filter_output(raw: object, *, filename_stem: str) -> ExtractionOutput:
    if not isinstance(raw, dict):
        raise InvalidOutput("not an object")
    summary, ents, rels = raw.get("summary", ""), raw.get("entities", []), raw.get("relations", [])
    if not isinstance(summary, str) or not isinstance(ents, list) or not isinstance(rels, list):
        raise InvalidOutput("wrong field types")
    stem = norm(filename_stem)
    entities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in ents:
        if not isinstance(item, dict) or item.get("type") not in ENTITY_TYPES:
            continue
        name = _clean(item.get("name"))
        key = norm(name)
        if not key or key == stem or key in seen:
            continue
        seen.add(key)
        aliases = [
            a
            for a in (_clean(x) for x in item.get("aliases") or [] if isinstance(x, str))
            if norm(a)
        ]
        entities.append(
            {
                "name": name,
                "type": item["type"],
                "aliases": aliases[:MAX_ALIASES],
                "confidence": _clamp(item.get("confidence")),
            }
        )
        if len(entities) == MAX_ENTITIES:
            break
    known = {norm(e["name"]) for e in entities}
    relations: list[dict[str, Any]] = []
    for item in rels:
        if not isinstance(item, dict) or item.get("relation") not in RELATIONS:
            continue
        subject, obj = _clean(item.get("subject")), _clean(item.get("object"))
        if (subject != "NOTE" and norm(subject) not in known) or norm(obj) not in known:
            continue
        chunk = item.get("chunk") if isinstance(item.get("chunk"), str) else None
        relations.append(
            {
                "subject": subject,
                "relation": item["relation"],
                "object": obj,
                "chunk": chunk,
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
