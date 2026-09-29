"""Argon2id password hashing for the single owner account."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(password_hash: str, plain: str) -> bool:
    """True only for a correct password. Mismatches and malformed hashes return False."""
    try:
        return _hasher.verify(password_hash, plain)
    except (VerificationError, InvalidHashError):
        return False
