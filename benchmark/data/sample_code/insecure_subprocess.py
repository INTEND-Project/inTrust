"""
Frozen benchmark input file — DO NOT FIX the issues in this file.

This file intentionally contains security issues that Bandit detects:
- B602: subprocess call with shell=True
- B605: os.system with shell injection potential
- B404/B603: subprocess import and untrusted input

The file is committed so that every benchmark run scans byte-identical
input, making the Bandit assessment fully reproducible.
"""

import os
import subprocess  # Bandit B404


def run_user_command(command: str) -> int:
    """Run an arbitrary user-supplied command through the shell."""
    return subprocess.call(command, shell=True)  # Bandit B602


def ping(host: str) -> int:
    """Ping a host by interpolating unvalidated input into a shell string."""
    return os.system("ping -c 1 " + host)  # Bandit B605
