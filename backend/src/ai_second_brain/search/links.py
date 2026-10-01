"""obsidian://open links. Obsidian must be installed on the device that opens them."""

from urllib.parse import quote


def obsidian_url(vault_name: str, path: str) -> str | None:
    if not vault_name:
        return None
    return f"obsidian://open?vault={quote(vault_name, safe='')}&file={quote(path, safe='')}"
