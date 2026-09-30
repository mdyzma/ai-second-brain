from ai_second_brain.knowledge.embed_text import embed_input
from ai_second_brain.vault.moves import guard_trips, pair_moves

H1, H2, H3 = b"1" * 32, b"2" * 32, b"3" * 32


def test_single_move_pairs() -> None:
    pairs, gone, new = pair_moves({"a/x.md": H1}, {"b/x.md": H1})
    assert (pairs, gone, new) == ([("a/x.md", "b/x.md")], [], [])


def test_unpaired_both_ways() -> None:
    pairs, gone, new = pair_moves({"a.md": H1}, {"b.md": H2})
    assert (pairs, gone, new) == ([], ["a.md"], ["b.md"])


def test_most_shared_prefix_wins_then_lexical() -> None:
    deleted = {"Projects/NAS/x.md": H1, "Archive/x.md": H1, "Projects/Other/x.md": H1}
    pairs, gone, _ = pair_moves(deleted, {"Projects/NAS/y.md": H1})
    assert pairs == [("Projects/NAS/x.md", "Projects/NAS/y.md")]
    assert gone == ["Archive/x.md", "Projects/Other/x.md"]
    pairs, _, _ = pair_moves({"b/x.md": H3, "a/x.md": H3}, {"c/x.md": H3})
    assert pairs == [("a/x.md", "c/x.md")]


def test_case_only_rename_pairs() -> None:
    assert pair_moves({"Note.md": H1}, {"note.md": H1})[0] == [("Note.md", "note.md")]


def test_guard() -> None:
    assert guard_trips(10, 40) is False
    assert guard_trips(11, 40) is True
    assert guard_trips(11, 100) is False
    assert guard_trips(0, 0) is False


def test_embed_input() -> None:
    assert embed_input("NAS", ["Disks", "RAID"], "text") == "NAS › Disks › RAID\n\ntext"
    assert embed_input("NAS", [], "text") == "NAS\n\ntext"
