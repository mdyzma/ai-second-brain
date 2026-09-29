import json
from typing import Any


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    """Parse a complete SSE body into (event, data) pairs; comment lines are skipped."""
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        lines = [line for line in block.split("\n") if line and not line.startswith(":")]
        if not lines:
            continue
        name = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        events.append((name, json.loads(data)))
    return events
