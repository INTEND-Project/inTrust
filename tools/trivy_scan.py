import subprocess
import json
import os
import platform
import time
from pathlib import Path
from typing import Dict, Any

TRIVY_BIN = os.path.join(Path(__file__).parent.parent, "bin", "trivy.exe")
TRIVY_VERSION = "0.59.1"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / os.getenv(
    "INTRUST_STORAGE_DIR", "storage"
)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

#def get_bin():
#    """Ensure the Trivy binary exists."""
#    print(os.path.join(Path(__file__).parent.parent))
#    print(TRIVY_BIN)
#    if not os.path.exists(TRIVY_BIN):
#        raise FileNotFoundError("Trivy binary not found. Ensure it is packaged correctly.")
#    return TRIVY_BIN

def get_bin():
    """Return the correct Trivy binary depending on the operating system."""
    base_dir = Path(__file__).parent.parent / "bin"

    # Detect OS type
    if platform.system().lower().startswith("win"):
        trivy_bin = base_dir / "trivy.exe"
    else:
        trivy_bin = base_dir / "trivy"

    print(f"Detected OS: {platform.system()}")
    print(f"Using Trivy binary: {trivy_bin}")

    if not trivy_bin.exists():
        raise FileNotFoundError(
            f"Trivy binary not found at {trivy_bin}. Ensure it is included in the package."
        )

    # Ensure execution permission on Unix-like systems
    if platform.system().lower() != "windows":
        trivy_bin.chmod(0o755)

    return str(trivy_bin)


def _run_trivy_command(
    cmd: list, output_file: str, logger: Any | None = None
) -> Dict[str, Any]:
    """Run a Trivy command and return parsed JSON results."""
    if logger:
        logger.info(
            "subprocess",
            "[Subprocess]\nExecuting command:\n" + " ".join(str(part) for part in cmd),
        )
    start_time = time.time()
    process = subprocess.run(cmd, capture_output=True, text=True, check=False)
    elapsed_time = round(time.time() - start_time, 2)

    if process.returncode not in [0]:
        raise RuntimeError(f"Trivy scan failed: {process.stderr.strip()}")

    if not os.path.exists(output_file):
        raise FileNotFoundError(f"Expected output file not found: {output_file}")

    with open(output_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data, elapsed_time


def _summarize_trivy_results(data: Dict[str, Any]) -> Dict[str, int]:
    """Count concrete Trivy findings across all result targets."""
    summary = {
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
    Handles a TMForum intent for scanning Docker images.
    Expected input:
    {
        "intentId": "intent-001",
        "parameters": { "dockerImage": "python:3.11-slim" }
    }
    """
    try:
        intent_id = intent_request.get("intentId", "unknown")
        params = intent_request.get("parameters", {})
        docker_image = params.get("dockerImage")

        if not docker_image:
            raise ValueError("Missing required parameter: dockerImage")

        print(f"[Trivy] Scanning Docker image: {docker_image}")
        trivy_path = get_bin()

        output_file = str(OUTPUT_DIR / f"scan-image-{intent_id}.json")
        cmd = [
            trivy_path, "image",
            "--exit-code", "0",
            "--format", "json",
            "-o", output_file,
            "--timeout", "12m0s",
            "--cache-dir", "cache/",
            "--severity", "HIGH,CRITICAL",
            docker_image
        ]

        data, elapsed_time = _run_trivy_command(cmd, output_file, logger)

        # Summary extraction
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
                f"Detected {vuln_count} vulnerable components in image {docker_image}."
                if vuln_count > 0 else "No vulnerabilities found."
            ),
        }

    except Exception as e:
        print(f"[ERROR] Docker image scan failed: {e}")
        return {"status": "FAILED", "error": str(e)}


def scan_fs(intent_request: Dict[str, Any], logger: Any | None = None) -> Dict[str, Any]:
    """
    Handles a TMForum intent for scanning local filesystem paths.
    Expected input:
    {
        "intentId": "intent-002",
        "parameters": { "fsPath": "/opt/project" }
    }
    """
    try:
        intent_id = intent_request.get("intentId", "unknown")
        params = intent_request.get("parameters", {})
        fs_path = params.get("fsPath")

        if not fs_path or not os.path.exists(fs_path):
            raise FileNotFoundError(f"Invalid or missing fsPath: {fs_path}")

        print(f"[Trivy] Scanning filesystem path: {fs_path}")
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
            "--scanners", "vuln,secret,misconfig",
            fs_path
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
                f"Detected {issue_count} potential issues in {fs_path}."
                if issue_count > 0 else "No critical issues found."
            ),
        }

    except Exception as e:
        print(f"[ERROR] Filesystem scan failed: {e}")
        return {"status": "FAILED", "error": str(e)}


def scan_k8_cluster(
    intent_request: Dict[str, Any], logger: Any | None = None
) -> Dict[str, Any]:
    """
    Handles a TMForum intent for scanning Kubernetes clusters.
    Expected input:
    {
        "intentId": "intent-003",
        "parameters": { "clusterName": "my-cluster" }
    }
    """
    try:
        intent_id = intent_request.get("intentId", "unknown")
        params = intent_request.get("parameters", {})
        cluster_name = params.get("clusterName")

        if not cluster_name:
            raise ValueError("Missing required parameter: clusterName")

        print(f"[Trivy] Scanning Kubernetes cluster: {cluster_name}")
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
            "--report", "all",
            cluster_name
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
                f"Detected {issue_count} security findings in cluster {cluster_name}."
                if issue_count > 0 else "No major misconfigurations or vulnerabilities detected."
            ),
        }

    except Exception as e:
        print(f"[ERROR] Kubernetes scan failed: {e}")
        return {"status": "FAILED", "error": str(e)}


# Example usage for local testing
if __name__ == "__main__":
    docker_test = {"intentId": "intent-001", "parameters": {"dockerImage": "python:3.11-slim"}}
    fs_test = {"intentId": "intent-002", "parameters": {"fsPath": "./"}}
    k8_test = {"intentId": "intent-003", "parameters": {"clusterName": "my-cluster"}}

    print(json.dumps(scan_docker_image(docker_test), indent=2))
    print(json.dumps(scan_fs(fs_test), indent=2))
    print(json.dumps(scan_k8_cluster(k8_test), indent=2))
