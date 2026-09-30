from collections.abc import Sequence


def embed_input(title: str, heading_path: Sequence[str], content: str) -> str:
    head = " › ".join([title, *heading_path])
    return f"{head}\n\n{content}"
