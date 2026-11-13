# Copyright (c) 2025-2026 SINTEF Digital
# Copyright (c) 2026 Ericsson AB
#   Ericsson AB: normalises Trivy output into canonical facts before it leaves
#     the skill.
# SPDX-License-Identifier: MIT
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
from orchestrator.skill_result import normalised_result
from tools.trivy_normalizer import normalize
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
        ``{status, assessment_type, tool, facts, raw}`` — the canonical facts
        every audience rendition is projected from, beside the unmodified Trivy
        output they were derived from.
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
        return result

    logger.info("skill.trivy_image", result.get("explanation", "Trivy image scan completed"))

    # Normalise before the result leaves the skill.  Deriving the findings here
    # rather than leaving Trivy's raw container image report for the
    # report-composing model to read is what keeps every audience rendition
    # traceable to the same findings — and it is where the scan's severity
    # filter (HIGH,CRITICAL only) is recorded as a stated scope limitation, so a
    # clean result is never reported as an unqualified all-clear.
    facts = normalize(result, intent=intent)
    return normalised_result(
        facts,
        raw_result=result,
        assessment_type="docker_image_security",
        tool="Trivy",
        logger=logger,
        component="skill.trivy_image",
    )


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
