import pytest

from ai_second_brain.auth.passwords import hash_password, verify_password

POLISH = "zażółć gęślą jaźń 🔑 "  # trailing space is part of the password


def test_round_trip() -> None:
    hashed = hash_password("s3cret")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "s3cret")


def test_wrong_password_is_false() -> None:
    assert not verify_password(hash_password("s3cret"), "S3cret")


def test_non_ascii_and_whitespace_are_significant() -> None:
    hashed = hash_password(POLISH)
    assert verify_password(hashed, POLISH)
    assert not verify_password(hashed, POLISH.strip())
    assert not verify_password(hashed, "zazolc gesla jazn 🔑 ")


@pytest.mark.parametrize("bad_hash", ["", "not-a-hash", "$argon2id$v=19$broken"])
def test_malformed_hash_is_false_not_error(bad_hash: str) -> None:
    assert verify_password(bad_hash, "anything") is False


def test_hashes_are_salted() -> None:
    assert hash_password("same") != hash_password("same")
