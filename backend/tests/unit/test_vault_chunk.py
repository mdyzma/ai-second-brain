from ai_second_brain.vault.chunk import MAX_CHARS, OVERLAP, chunk_note


def words(n: int, word: str = "słowo") -> str:
    return " ".join([word] * n)


def test_heading_paths_and_fences() -> None:
    body = (
        "intro text\n"
        "# Projects\n"
        "top\n"
        "## NAS\n"
        "disks\n"
        "```bash\n# not a heading\n```\n"
        "### Deep\n"
        "deep\n"
        "## Backups\n"
        "nightly\n"
    )
    chunks = chunk_note(body)
    assert [(c.heading_path, c.content) for c in chunks] == [
        ((), "intro text"),
        (("Projects",), "top"),
        (("Projects", "NAS"), "disks\n```bash\n# not a heading\n```"),
        (("Projects", "NAS", "Deep"), "deep"),
        (("Projects", "Backups"), "nightly"),
    ]
    assert [c.ordinal for c in chunks] == [0, 1, 2, 3, 4]


def test_empty_sections_dropped_and_headingless_note() -> None:
    assert [c.content for c in chunk_note("# Empty\n\n# Full\ntext\n")] == ["text"]
    assert chunk_note("") == []
    assert chunk_note("  \n\n ") == []
    assert [c.heading_path for c in chunk_note("just text\n\nmore")] == [()]


def test_boundary_1600_is_one_chunk_1601_splits() -> None:
    exact = "a" * MAX_CHARS
    assert [c.content for c in chunk_note(exact)] == [exact]
    over = words(400)  # well over 1600 chars, no paragraph breaks
    chunks = chunk_note(over)
    assert len(chunks) > 1
    assert all(len(c.content) <= MAX_CHARS for c in chunks)


def test_paragraph_packing_and_overlap() -> None:
    paragraphs = [f"Paragraf {i}. " + words(40) for i in range(12)]
    chunks = chunk_note("\n\n".join(paragraphs))
    assert len(chunks) >= 3
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert len(current.content) <= MAX_CHARS
        # The chunk starts with a non-empty suffix (≤ OVERLAP chars) of the previous chunk.
        overlaps = [
            k for k in range(1, OVERLAP + 1) if current.content.startswith(previous.content[-k:])
        ]
        assert overlaps, "continuation chunk must start with the tail of the previous chunk"
        assert max(overlaps) >= 20
        assert not current.content.startswith(" ")


def test_long_sentence_is_hard_split() -> None:
    chunks = chunk_note("x" * 5000)
    assert all(len(c.content) <= MAX_CHARS for c in chunks)
    overlaps = sum(len(c.content.split("\n\n")[0]) for c in chunks[1:])
    assert "".join(c.content for c in chunks).count("x") == 5000 + overlaps
    assert all(" " not in c.content for c in chunks)


def test_hard_split_never_injects_space_into_long_token() -> None:
    chunks = chunk_note("a" * 1450 + "\n\n" + "b " * 400)
    assert all(len(c.content) <= MAX_CHARS for c in chunks)
    assert "a" * 1450 in chunks[0].content
    assert " " not in chunks[0].content.split("\n\n")[0]


def test_trailing_hash_kept_unless_closing_sequence() -> None:
    def path(heading: str) -> tuple[str, ...]:
        return chunk_note(f"{heading}\ntext")[0].heading_path

    assert path("# Learning C#") == ("Learning C#",)
    assert path("# Title ##") == ("Title",)
    assert path("## F# notes #") == ("F# notes",)
