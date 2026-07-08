"""Frozen benchmark input — unsafe deserialization (Bandit: B301, B506)."""

import pickle

import yaml


def load_session(raw: bytes):
    # Deserialising untrusted data with pickle.
    return pickle.loads(raw)


def load_config(text: str):
    # yaml.load without SafeLoader can instantiate arbitrary objects.
    return yaml.load(text)
