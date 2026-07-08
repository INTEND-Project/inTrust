"""Frozen benchmark input — insecure network usage (Bandit: B501, B310)."""

import urllib.request

import requests


def fetch_report(url: str):
    # TLS certificate verification disabled.
    return requests.get(url, verify=False)


def download_update(path: str):
    # urlopen with an audit-flagged URL scheme.
    return urllib.request.urlopen("http://updates.example.com/" + path)
