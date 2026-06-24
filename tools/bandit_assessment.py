import subprocess
import json
import os
import time
from typing import Dict, Any


def _log_subprocess(logger: Any, command: list[str]) -> None:
    if logger:
        logger.info(
            "subprocess",
            "[Subprocess]\nExecuting command:\n" + " ".join(command),
        )


def run_bandit_assessment(
    intent_request: Dict[str, Any], logger: Any | None = None
) -> Dict[str, Any]:
    """
    Handles a TMForum intent requesting security vulnerability assessment
    for a Python code artifact using Bandit.
    
    Expected input example:
        {
            "intentId": "intent-456",
            "parameters": {
                "codeReference": { "path": "/path/to/codebase" }
            }
        }
    """

    try:
        intent_id = intent_request.get("intentId", "unknown")
        params = intent_request.get("parameters", {})
        code_ref = params.get("codeReference", {})
        code_path = code_ref.get("path")

        if not code_path or not os.path.exists(code_path):
            raise FileNotFoundError(f"Code path not found: {code_path}")

        print(f"Running Bandit assessment for intent: {intent_id}")
        print(f"Target code path: {code_path}")

        # --- Step 1: Run Bandit ---
        # Run Bandit as a subprocess to analyze the code
        command = ["bandit", "-r", code_path, "-f", "json", "-q"]
        _log_subprocess(logger, command)
        start_time = time.time()
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False
        )
        elapsed_time = time.time() - start_time

        if process.returncode not in [0, 1]:  # 0: no issues, 1: found issues
            raise RuntimeError(f"Bandit execution failed: {process.stderr}")

        # --- Step 2: Parse results ---
        bandit_output = json.loads(process.stdout or "{}")
        results = bandit_output.get("results", [])
        metrics = bandit_output.get("metrics", {})

        issue_count = len(results)
        high_severity = sum(1 for r in results if r["issue_severity"] == "HIGH")
        medium_severity = sum(1 for r in results if r["issue_severity"] == "MEDIUM")
        low_severity = sum(1 for r in results if r["issue_severity"] == "LOW")

        # --- Step 3: Determine assessment ---
        assessment = "secure"
        if high_severity > 0 or medium_severity > 2:
            assessment = "vulnerable"

        explanation = (
            f"Found {issue_count} total issues "
            f"({high_severity} high, {medium_severity} medium, {low_severity} low)."
        )

        # --- Step 4: Build structured report ---
        result = {
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

        return result

    except Exception as e:
        print("Error while running Bandit assessment:", str(e))
        return {
            "status": "FAILED",
            "error": str(e),
        }


# Example usage for debugging:
if __name__ == "__main__":
    test_request = {
        "intentId": "intent-demo-789",
        "parameters": {
            "codeReference": {"path": "./orchestrator/agent.py"}
        }
    }

    report = run_bandit_assessment(test_request)
    print(json.dumps(report, indent=2))
