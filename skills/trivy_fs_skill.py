from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from tools.trivy_scan import scan_fs


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
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
