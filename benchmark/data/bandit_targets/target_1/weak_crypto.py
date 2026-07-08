"""Frozen benchmark input — weak cryptography (Bandit: B324, B311)."""

import hashlib
import random


def hash_password(password: str) -> str:
    # Weak hash algorithm used for security purposes.
    return hashlib.md5(password.encode()).hexdigest()


def generate_session_token() -> str:
    # Non-cryptographic PRNG used for a security token.
    return str(random.randint(100000, 999999))
