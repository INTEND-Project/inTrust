"""Frozen benchmark input — shell execution and temp files (Bandit: B602, B306)."""

import subprocess
import tempfile


def run_backup(directory: str):
    # Shell injection: user input concatenated into a shell command.
    return subprocess.call("tar czf /tmp/backup.tgz " + directory, shell=True)


def scratch_file() -> str:
    # mktemp is vulnerable to symlink races.
    return tempfile.mktemp()
