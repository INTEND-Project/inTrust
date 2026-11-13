# Copyright (c) 2025-2026 SINTEF Digital
# Copyright (c) 2026 Ericsson AB
#   Ericsson AB: normalises Trivy output into canonical facts before it leaves
#     the skill.
# SPDX-License-Identifier: MIT
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
from orchestrator.skill_result import normalised_result
from tools.trivy_normalizer import normalize
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
        ``{status, assessment_type, tool, facts, raw}`` — the canonical facts
        every audience rendition is projected from, beside the unmodified Trivy
        output they were derived from.
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
        return result

    logger.info("skill.trivy_fs", result.get("explanation", "Trivy filesystem scan completed"))

    # Normalise before the result leaves the skill.  Deriving the findings here
    # rather than leaving Trivy's raw output for the report-composing model to
    # read is what keeps every audience rendition traceable to the same findings
    # — and it is where the scan's severity filter (HIGH,CRITICAL only) is
    # recorded as a stated scope limitation, so a clean result is never reported
    # as an unqualified all-clear.
    facts = normalize(result, intent=intent)
    return normalised_result(
        facts,
        raw_result=result,
        assessment_type="filesystem_security",
        tool="Trivy",
        logger=logger,
        component="skill.trivy_fs",
    )


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
