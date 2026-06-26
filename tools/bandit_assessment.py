"""
Bandit tool wrapper.

This module provides the low-level interface for running the Bandit security
linter as a subprocess.  It is called by the ``bandit-static-code`` skill.

Bandit analyses Python source code for common security issues such as use of
dangerous functions, hardcoded passwords, SQL injection patterns, and insecure
use of cryptographic primitives.  It returns findings categorised by severity
(HIGH, MEDIUM, LOW) and confidence.

The assessment verdict logic is:
- ``"vulnerable"`` if there is at least one HIGH severity issue, or more
  than two MEDIUM severity issues.
- ``"secure"`` otherwise.
"""

import json
import os
import subprocess
import time
from typing import Any, Dict


def _log_subprocess(logger: Any, command: list[str]) -> None:
    """Log the command that is about to be executed, if a logger is provided."""
    if logger:
        logger.info(
            "subprocess",
            "[Subprocess]\nExecuting command:\n" + " ".join(command),
        )


def run_bandit_assessment(
    intent_request: Dict[str, Any], logger: Any | None = None
) -> Dict[str, Any]:
    """
    Run Bandit against a Python source tree and return a structured report.

    Parameters
    ----------
    intent_request : dict
        TM Forum Intent.  The code path is read from
        ``parameters.codeReference.path``.
    logger : JobLogger, optional
        If provided, progress and subprocess commands are logged through it.

    Returns
    -------
    dict
        On success: a report with ``status="SUCCESS"``, severity counts,
        assessment verdict, explanation, and recommendations.
        On failure: ``{"status": "FAILED", "error": "<message>"}``.
    """
    try:
        intent_id = intent_request.get("intentId", "unknown")
        params = intent_request.get("parameters", {})
        code_ref = params.get("codeReference", {})
        code_path = code_ref.get("path")

        if not code_path or not os.path.exists(code_path):
            raise FileNotFoundError(f"Code path not found: {code_path!r}")

        if logger:
            logger.info(
                "tool.bandit",
                f"Running Bandit assessment for intent: {intent_id}\n"
                f"Target code path: {code_path}",
            )

        # Run Bandit recursively on the target directory.
        # -f json: machine-readable output.
        # -q: suppress the progress bar so stdout is clean JSON.
        # Return code 0 means no issues; 1 means issues were found.
        # Any other return code indicates a Bandit execution error.
        command = ["bandit", "-r", code_path, "-f", "json", "-q"]
        _log_subprocess(logger, command)
        start_time = time.time()
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed_time = time.time() - start_time

        if process.returncode not in [0, 1]:
            raise RuntimeError(f"Bandit execution failed: {process.stderr}")

        # Parse the JSON output.  Bandit always writes valid JSON when
        # invoked with -f json, even if no issues are found.
        bandit_output = json.loads(process.stdout or "{}")
        results = bandit_output.get("results", [])

        issue_count = len(results)
        high_severity = sum(1 for r in results if r["issue_severity"] == "HIGH")
        medium_severity = sum(1 for r in results if r["issue_severity"] == "MEDIUM")
        low_severity = sum(1 for r in results if r["issue_severity"] == "LOW")

        # Determine the overall security verdict.
        # The threshold (>2 MEDIUM issues) is intentionally lenient to reduce
        # false positives in research codebases with low-risk patterns.
        assessment = "secure"
        if high_severity > 0 or medium_severity > 2:
            assessment = "vulnerable"

        explanation = (
            f"Found {issue_count} total issues "
            f"({high_severity} high, {medium_severity} medium, {low_severity} low)."
        )

        return {
            "intentId": intent_id,
            "status": "SUCCESS",
            "assessment_type": "static_code_analysis",
            "tool": "Bandit",
            "execution_time_sec": round(elapsed_time, 2),
            "issue_summary": {
                "total": issue_count,
                "high": high_severity,
                "medium": medium_severity,
                "low": low_severity,
            },
            "assessment": assessment,
            "explanation": explanation,
            "recommendations": (
                "Review high and medium severity issues. "
                "Apply secure coding guidelines and rerun Bandit."
                if assessment == "vulnerable"
                else "No major vulnerabilities detected."
            ),
        }

    except Exception as exc:
        if logger:
            logger.error("tool.bandit", f"Bandit assessment error: {exc}")
        return {
            "status": "FAILED",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Quick manual test — run this file directly to test without the HTTP server:
#   python tools/bandit_assessment.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    test_request = {
        "intentId": "intent-demo-789",
        "parameters": {
            "codeReference": {"path": "./orchestrator/agent.py"}
        },
    }
    report = run_bandit_assessment(test_request)
    print(json.dumps(report, indent=2))
