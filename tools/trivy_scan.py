"""
Trivy tool wrappers.

This module provides the low-level functions for running the Trivy security
scanner as a subprocess.  It is called by the three Trivy-based skills
(trivy-docker-image, trivy-filesystem, trivy-kubernetes).

Trivy is an open-source vulnerability scanner that can analyse:
- Docker / OCI container images (packages, OS layers, application deps)
- Local filesystem paths (source code, lock files, configs)
- Kubernetes clusters (running workloads, misconfigurations)

The Trivy binary is expected to be bundled inside the project's ``bin/``
directory.  ``get_bin()`` selects the correct filename for the current OS.

All scan functions write Trivy's JSON output to a file in the storage
directory (configurable via INTRUST_STORAGE_DIR) and then parse it.
Writing to a file rather than reading stdout avoids issues with large
outputs that might be truncated in a pipe.
"""

import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Tuple

# The Trivy binary is stored in the project's bin/ directory.
# get_bin() returns the correct path for the current OS.
_BIN_DIR = Path(__file__).parent.parent / "bin"

# Trivy version embedded in result records for traceability.
TRIVY_VERSION = "0.59.1"

# Directory where Trivy writes its raw JSON output files.
# Each scan produces a separate file named after the intent ID.
OUTPUT_DIR = Path(__file__).resolve().parent.parent / os.getenv(
    "INTRUST_STORAGE_DIR", "storage"
)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_bin() -> str:
    """
    Return the path to the Trivy binary for the current operating system.

    On Windows the binary is named ``trivy.exe``; on Linux/macOS it has no
    extension.  The function also sets the executable bit on Unix systems in
    case the file was created without it (e.g. after a Docker volume mount).

    Raises
    ------
    FileNotFoundError
        If the Trivy binary is not present in the ``bin/`` directory.
    """
    if platform.system().lower().startswith("win"):
        trivy_bin = _BIN_DIR / "trivy.exe"
    else:
        trivy_bin = _BIN_DIR / "trivy"

    if not trivy_bin.exists():
        raise FileNotFoundError(
            f"Trivy binary not found at {trivy_bin}. "
            "Ensure it is included in the bin/ directory "
            "(the Dockerfile downloads it automatically)."
        )

    # Ensure the binary is executable on Unix-like systems.  Only attempt the
    # chmod when the executable bit is actually missing: the binary may be a
    # symlink to a system-owned file (e.g. /usr/bin/trivy) that we are not
    # permitted to chmod.  Following such a symlink would raise EPERM
    # ("Operation not permitted"), so we skip the chmod when it is unnecessary
    # and tolerate failures when it is already runnable.
    if platform.system().lower() != "windows":
        # stat() follows symlinks, so this reflects the real target's mode.
        if not os.access(trivy_bin, os.X_OK):
            try:
                trivy_bin.chmod(0o755)
            except PermissionError as exc:
                raise PermissionError(
                    f"Trivy binary at {trivy_bin} is not executable and its "
                    "permissions could not be changed. Make it executable "
                    "(chmod +x) or point it at a runnable binary."
                ) from exc

    return str(trivy_bin)


def _run_trivy_command(
    cmd: list,
    output_file: str,
    logger: Any | None = None,
) -> Tuple[Dict[str, Any], float]:
    """
    Execute a Trivy command and return its parsed JSON output.

    Parameters
    ----------
    cmd : list
        The full command line including the Trivy binary path and all flags.
    output_file : str
        Path where Trivy will write its JSON results (passed via -o flag).
    logger : JobLogger, optional
        If provided, the command is logged before execution.

    Returns
    -------
    (data, elapsed_time)
        ``data`` is the parsed JSON dict; ``elapsed_time`` is the wall-clock
        duration in seconds.

    Raises
    ------
    RuntimeError
        If Trivy exits with a non-zero return code.
    FileNotFoundError
        If the expected output file was not created.
    """
    if logger:
        logger.info(
            "subprocess",
            "[Subprocess]\nExecuting command:\n" + " ".join(str(part) for part in cmd),
        )

    start_time = time.time()
    process = subprocess.run(cmd, capture_output=True, text=True, check=False)
    elapsed_time = round(time.time() - start_time, 2)

    # Trivy exits with 0 on success.  Unlike Bandit it does not use exit
    # code 1 to signal findings (we pass --exit-code 0 to disable that).
    if process.returncode != 0:
        raise RuntimeError(f"Trivy scan failed: {process.stderr.strip()}")

    if not os.path.exists(output_file):
        raise FileNotFoundError(f"Expected Trivy output file not found: {output_file}")

    with open(output_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data, elapsed_time


def _summarize_trivy_results(data: Dict[str, Any]) -> Dict[str, int]:
    """
    Aggregate finding counts across all scan targets in a Trivy JSON report.

    Trivy organises results into a list of ``Results`` entries, one per
    scanned target (e.g. a Docker layer, a lock file, a K8s namespace).
    This function flattens those into simple total counts.

    Returns a dict with keys:
    ``vulnerabilities``, ``secrets``, ``misconfigurations``, ``licenses``,
    ``targets`` (number of scan targets), ``total_findings``.
    """
    summary: Dict[str, int] = {
        "vulnerabilities": 0,
        "secrets": 0,
        "misconfigurations": 0,
        "licenses": 0,
        "targets": len(data.get("Results", [])),
    }
    for result in data.get("Results", []):
        summary["vulnerabilities"] += len(result.get("Vulnerabilities", []) or [])
        summary["secrets"] += len(result.get("Secrets", []) or [])
        summary["misconfigurations"] += len(result.get("Misconfigurations", []) or [])
        summary["licenses"] += len(result.get("Licenses", []) or [])

    summary["total_findings"] = (
        summary["vulnerabilities"]
        + summary["secrets"]
        + summary["misconfigurations"]
        + summary["licenses"]
    )
    return summary


def scan_docker_image(
    intent_request: Dict[str, Any], logger: Any | None = None
) -> Dict[str, Any]:
    """
    Scan a Docker image for HIGH and CRITICAL severity vulnerabilities.

    Parameters
    ----------
    intent_request : dict
        TM Forum Intent.  Must contain ``parameters.dockerImage``.
    logger : JobLogger, optional
        Bound job logger.

    Returns
    -------
    dict
        Assessment result with vulnerability counts, verdict, and explanation.
    """
    try:
        intent_id = intent_request.get("intentId", "unknown")
        docker_image = intent_request.get("parameters", {}).get("dockerImage")

        if not docker_image:
            raise ValueError("Missing required parameter: dockerImage")

        if logger:
            logger.info("tool.trivy", f"Scanning Docker image: {docker_image}")

        trivy_path = get_bin()
        output_file = str(OUTPUT_DIR / f"scan-image-{intent_id}.json")

        cmd = [
            trivy_path, "image",
            "--exit-code", "0",       # Do not exit with 1 when findings exist.
            "--format", "json",
            "-o", output_file,
            "--timeout", "12m0s",
            "--cache-dir", "cache/",
            "--severity", "HIGH,CRITICAL",
            docker_image,
        ]

        data, elapsed_time = _run_trivy_command(cmd, output_file, logger)
        summary = _summarize_trivy_results(data)
        vuln_count = summary["vulnerabilities"]
        assessment = "secure" if vuln_count == 0 else "vulnerable"

        return {
            "intentId": intent_id,
            "status": "SUCCESS",
            "assessment_type": "docker_image_security",
            "tool": "Trivy",
            "version": TRIVY_VERSION,
            "execution_time_sec": elapsed_time,
            "target": docker_image,
            "metrics": summary,
            "assessment": assessment,
            "explanation": (
                f"Detected {vuln_count} vulnerable component(s) in image {docker_image}."
                if vuln_count > 0
                else f"No HIGH or CRITICAL vulnerabilities found in image {docker_image}."
            ),
            "recommendations": (
                "Update the affected base image and dependency packages."
                if vuln_count > 0
                else "Image appears secure against known HIGH/CRITICAL vulnerabilities."
            ),
        }

    except Exception as exc:
        if logger:
            logger.error("tool.trivy", f"Docker image scan failed: {exc}")
        return {"status": "FAILED", "error": str(exc)}


def scan_fs(
    intent_request: Dict[str, Any], logger: Any | None = None
) -> Dict[str, Any]:
    """
    Scan a local filesystem path for vulnerabilities, secrets, and
    misconfigurations.

    Parameters
    ----------
    intent_request : dict
        TM Forum Intent.  Must contain ``parameters.fsPath``.
    logger : JobLogger, optional
        Bound job logger.

    Returns
    -------
    dict
        Assessment result with finding counts, verdict, and explanation.
    """
    try:
        intent_id = intent_request.get("intentId", "unknown")
        fs_path = intent_request.get("parameters", {}).get("fsPath")

        if not fs_path or not os.path.exists(fs_path):
            raise FileNotFoundError(f"Invalid or missing fsPath: {fs_path!r}")

        if logger:
            logger.info("tool.trivy", f"Scanning filesystem path: {fs_path}")

        trivy_path = get_bin()
        output_file = str(OUTPUT_DIR / f"scan-fs-{intent_id}.json")

        cmd = [
            trivy_path, "fs",
            "--exit-code", "0",
            "--format", "json",
            "-o", output_file,
            "--timeout", "12m0s",
            "--cache-dir", "cache/",
            "--severity", "HIGH,CRITICAL",
            "--scanners", "vuln,secret,misconfig",  # Enable all three scanner types.
            fs_path,
        ]

        data, elapsed_time = _run_trivy_command(cmd, output_file, logger)
        summary = _summarize_trivy_results(data)
        issue_count = summary["total_findings"]
        assessment = "secure" if issue_count == 0 else "vulnerable"

        return {
            "intentId": intent_id,
            "status": "SUCCESS",
            "assessment_type": "filesystem_security",
            "tool": "Trivy",
            "version": TRIVY_VERSION,
            "execution_time_sec": elapsed_time,
            "target": fs_path,
            "metrics": summary,
            "assessment": assessment,
            "explanation": (
                f"Detected {issue_count} potential issue(s) in {fs_path}."
                if issue_count > 0
                else f"No HIGH or CRITICAL issues found in {fs_path}."
            ),
            "recommendations": (
                "Review and remediate the identified vulnerabilities, secrets, "
                "and misconfigurations."
                if issue_count > 0
                else "Filesystem scan found no critical security issues."
            ),
        }

    except Exception as exc:
        if logger:
            logger.error("tool.trivy", f"Filesystem scan failed: {exc}")
        return {"status": "FAILED", "error": str(exc)}


def scan_k8_cluster(
    intent_request: Dict[str, Any], logger: Any | None = None
) -> Dict[str, Any]:
    """
    Scan a Kubernetes cluster for security misconfigurations and
    vulnerabilities.

    Parameters
    ----------
    intent_request : dict
        TM Forum Intent.  Must contain ``parameters.clusterName`` (the
        kubeconfig context name or cluster identifier).
    logger : JobLogger, optional
        Bound job logger.

    Returns
    -------
    dict
        Assessment result with security findings, verdict, and explanation.
    """
    try:
        intent_id = intent_request.get("intentId", "unknown")
        cluster_name = intent_request.get("parameters", {}).get("clusterName")

        if not cluster_name:
            raise ValueError("Missing required parameter: clusterName")

        if logger:
            logger.info("tool.trivy", f"Scanning Kubernetes cluster: {cluster_name}")

        trivy_path = get_bin()
        output_file = str(OUTPUT_DIR / f"scan-k8s-{intent_id}.json")

        cmd = [
            trivy_path, "k8s",
            "--exit-code", "0",
            "--format", "json",
            "-o", output_file,
            "--timeout", "12m0s",
            "--cache-dir", "cache/",
            "--severity", "HIGH,CRITICAL",
            "--report", "all",  # Include findings for every resource, not just a summary.
            cluster_name,
        ]

        data, elapsed_time = _run_trivy_command(cmd, output_file, logger)
        summary = _summarize_trivy_results(data)
        issue_count = summary["total_findings"]
        assessment = "secure" if issue_count == 0 else "vulnerable"

        return {
            "intentId": intent_id,
            "status": "SUCCESS",
            "assessment_type": "kubernetes_security",
            "tool": "Trivy",
            "version": TRIVY_VERSION,
            "execution_time_sec": elapsed_time,
            "target": cluster_name,
            "metrics": summary,
            "assessment": assessment,
            "explanation": (
                f"Detected {issue_count} security finding(s) in cluster {cluster_name}."
                if issue_count > 0
                else f"No major misconfigurations or vulnerabilities detected in cluster {cluster_name}."
            ),
            "recommendations": (
                "Review the identified misconfigurations and update affected workloads."
                if issue_count > 0
                else "Cluster appears compliant with assessed security controls."
            ),
        }

    except Exception as exc:
        if logger:
            logger.error("tool.trivy", f"Kubernetes scan failed: {exc}")
        return {"status": "FAILED", "error": str(exc)}


# ---------------------------------------------------------------------------
# Quick manual test — run this file directly to test without the HTTP server:
#   python tools/trivy_scan.py
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    docker_test = {"intentId": "intent-001", "parameters": {"dockerImage": "python:3.11-slim"}}
    fs_test = {"intentId": "intent-002", "parameters": {"fsPath": "./"}}
    k8_test = {"intentId": "intent-003", "parameters": {"clusterName": "my-cluster"}}

    print(json.dumps(scan_docker_image(docker_test), indent=2))
    print(json.dumps(scan_fs(fs_test), indent=2))
    print(json.dumps(scan_k8_cluster(k8_test), indent=2))
