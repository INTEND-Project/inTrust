"""
Trivy Docker image scanning skill.

This skill runs Trivy against a Docker (OCI) container image to detect
HIGH and CRITICAL severity vulnerabilities in the image's OS packages and
application dependencies.

Use it when the request asks for container security analysis, Docker image
vulnerability scanning, or OCI image assessment.

The intent must provide the image reference under ``parameters.dockerImage``
(e.g. ``"python:3.11-slim"`` or ``"registry.example.com/myapp:latest"``).

See also: docs/skills/trivy-docker-image.md
"""

from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from tools.trivy_scan import scan_docker_image


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    """
    Run Trivy image scan against the Docker image specified in the intent.

    Parameters
    ----------
    intent : dict
        TM Forum Intent.  Must contain ``parameters.dockerImage``.
    logger : JobLogger
        Bound logger for this job.

    Returns
    -------
    dict
        Assessment result with vulnerability counts, verdict, explanation,
        and recommendations.
    """
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
