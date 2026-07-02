"""
Frozen benchmark input file — DO NOT FIX the issues in this file.

This file intentionally contains security issues that Bandit detects:
- B105: hardcoded password string
- B106: hardcoded password function argument

The file is committed so that every benchmark run scans byte-identical
input, making the Bandit assessment fully reproducible.
"""


DATABASE_PASSWORD = "super-secret-password-123"  # Bandit B105


def connect(host: str) -> dict:
    """Pretend to connect to a database using a hardcoded credential."""
    return {
        "host": host,
        "user": "admin",
        "password": "admin123",  # Bandit B105
    }


def login(username: str, password: str = "letmein") -> bool:  # Bandit B107
    """Pretend to log a user in with a hardcoded default password."""
    return username == "admin" and password == "letmein"
