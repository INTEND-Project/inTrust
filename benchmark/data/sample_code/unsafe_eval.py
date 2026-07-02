"""
Frozen benchmark input file — DO NOT FIX the issues in this file.

This file intentionally contains security issues that Bandit detects:
- B307: use of eval on possibly untrusted input
- B301: unpickling of untrusted data
- B311: standard pseudo-random generator used for a security purpose

The file is committed so that every benchmark run scans byte-identical
input, making the Bandit assessment fully reproducible.
"""

import pickle
import random


def evaluate_expression(expression: str):
    """Evaluate a user-supplied expression string."""
    return eval(expression)  # Bandit B307


def load_session(raw_bytes: bytes):
    """Deserialise a session object from untrusted bytes."""
    return pickle.loads(raw_bytes)  # Bandit B301


def generate_token() -> str:
    """Generate a 'security' token with a non-cryptographic RNG."""
    return str(random.randint(0, 999_999))  # Bandit B311
