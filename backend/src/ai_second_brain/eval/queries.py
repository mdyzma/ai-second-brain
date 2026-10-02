"""Load and validate the owner's query set. Errors name query ids, never query text."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

ID = re.compile(r"^[a-z0-9-]{1,64}$")
LANGS = ("pl", "en")
KINDS = ("identifier", "paraphrase", "topic")
Lang = Literal["pl", "en"]
Kind = Literal["identifier", "paraphrase", "topic"]


class EvalConfigError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__(f"{len(errors)} problem(s) in the evaluation setup")
        self.errors = errors


@dataclass(frozen=True)
class EvalQuery:
    id: str
    q: str
    lang: str
    kind: str
    targets: tuple[str, ...]


def load_queries(path: Path) -> list[EvalQuery]:
    queries, errors = parse_queries(path)
    if errors:
        raise EvalConfigError(errors)
    return queries


def parse_queries(path: Path) -> tuple[list[EvalQuery], list[str]]:
    """The entries that validated, plus every error (file-level problems still raise)."""
    if not path.is_file():
        raise EvalConfigError([f"queries file not found: {path}"])
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise EvalConfigError(["queries file is not valid YAML"]) from None
    except (UnicodeDecodeError, OSError):
        raise EvalConfigError(["queries file could not be read as UTF-8 text"]) from None
    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or not isinstance(data.get("queries"), list)
    ):
        raise EvalConfigError(["queries file must be a mapping with version: 1 and a queries list"])
    errors: list[str] = []
    seen: set[str] = set()
    out: list[EvalQuery] = []
    for index, item in enumerate(data["queries"]):
        if not isinstance(item, dict):
            errors.append(f"#{index}: entry must be a mapping")
            continue
        before = len(errors)
        qid = str(item.get("id", f"#{index}"))
        if not ID.match(qid):
            errors.append(f"{qid}: id must match [a-z0-9-]{{1,64}}")
        if qid in seen:
            errors.append(f"{qid}: duplicate id")
        seen.add(qid)
        q = item.get("q")
        if not isinstance(q, str) or not q.strip() or len(q.strip()) > 500:
            errors.append(f"{qid}: q must be 1-500 characters (write a question)")
        if item.get("lang") not in LANGS:
            errors.append(f"{qid}: lang must be pl or en")
        if item.get("kind") not in KINDS:
            errors.append(f"{qid}: kind must be identifier, paraphrase or topic")
        targets = item.get("targets")
        if (
            not isinstance(targets, list)
            or not 1 <= len(targets) <= 10
            or not all(isinstance(t, str) and t.strip() for t in targets)
        ):
            errors.append(f"{qid}: targets must be 1-10 vault paths")
            targets = []
        if len(errors) > before:
            continue
        out.append(
            EvalQuery(
                qid,
                str(q or "").strip(),
                str(item.get("lang")),
                str(item.get("kind")),
                tuple(t.strip() for t in targets),
            )
        )
    return out, errors
