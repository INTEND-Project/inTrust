"""
Trivy filesystem scanning skill.

This skill runs Trivy against a local filesystem path to detect
vulnerabilities, exposed secrets, and misconfigurations in source code,
dependency lock files, and configuration files.

Use it when the request asks for filesystem security scanning, dependency
vulnerability analysis, secret detection, or infrastructure misconfiguration
checking on a local directory or mounted volume.

The intent must provide the filesystem path under ``parameters.fsPath``.

See also: docs/skills/trivy-filesystem.md
"""

from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from tools.trivy_scan import scan_fs


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    """
    Run Trivy filesystem scan against the path specified in the intent.

    Parameters
    ----------
    intent : dict
        TM Forum Intent.  Must contain ``parameters.fsPath``.
    logger : JobLogger
        Bound logger for this job.

    Returns
    -------
    dict
        Assessment result with counts of vulnerabilities, secrets, and
        misconfigurations, along with verdict, explanation, and
        recommendations.
    """
    target = intent.get("parameters", {}).get("fsPath")
    logger.info(
        "skill.trivy_fs",
        "[Skill Execution]\n"
        "Starting Trivy filesystem scan...\n"
        f"target={target}",
    )

    result = scan_fs(intent, logger)

    if result.get("status") == "FAILED":
        logger.error("skill.trivy_fs", result.get("error", "Trivy filesystem scan failed"))
    else:
        logger.info("skill.trivy_fs", result.get("explanation", "Trivy filesystem scan completed"))

    return result


SKILL = AssessmentSkill(
    name="trivy-filesystem",
    description="Runs Trivy filesystem scanning for vulnerabilities, secrets, and misconfigurations.",
    assessment_types=[
        "filesystem_security",
        "fs_scan",
        "dependency_security",
        "secret_scan",
        "misconfiguration",
        "trivy_fs",
    ],
    accepted_parameters=["fsPath"],
    execute=execute,
)
