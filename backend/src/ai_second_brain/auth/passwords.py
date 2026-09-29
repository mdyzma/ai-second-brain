from argon2 import PasswordHasher

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)
