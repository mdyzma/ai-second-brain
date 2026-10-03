import unicodedata


def norm(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).split()).casefold()
