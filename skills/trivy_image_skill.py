from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from tools.trivy_scan import scan_docker_image


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    target = intent.get("parameters", {}).get("dockerImage")
    logger.info(
        "skill.trivy_image",
        "[Skill Execution]\n"
        "Starting Docker image scan...\n"
        f"target={target}",
    )
    result = scan_docker_image(intent, logger)
    if result.get("status") == "FAILED":
        logger.error("skill.trivy_image", result.get("error", "Trivy image scan failed"))
    else:
        logger.info("skill.trivy_image", result.get("explanation", "Trivy image scan completed"))
    return result


SKILL = AssessmentSkill(
    name="trivy-docker-image",
    description="Runs Trivy image scanning against a Docker image.",
    assessment_types=[
        "docker_image_security",
        "container_security",
        "image_scan",
        "trivy_image",
        "docker",
    ],
    accepted_parameters=["dockerImage"],
    execute=execute,
)
