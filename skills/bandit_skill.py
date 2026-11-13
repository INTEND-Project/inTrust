# Copyright (c) 2025-2026 SINTEF Digital
# Copyright (c) 2026 Ericsson AB
#   Ericsson AB: normalises Bandit output into canonical facts before it
#     leaves the skill.
# SPDX-License-Identifier: MIT
"""
Bandit static code analysis skill.

This skill runs the Bandit security linter against a Python source tree.
Use it when the request asks for Python code security analysis, detection
of insecure coding patterns, or static application security testing (SAST).

The intent must provide the path to the Python code under
``parameters.codeReference.path``.

See also: docs/skills/bandit-static-code.md
"""

from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from orchestrator.skill_result import normalised_result
from tools.bandit_assessment import run_bandit_assessment
from tools.bandit_normalizer import normalize


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    """
    Run Bandit against the Python code path specified in the intent.

    Parameters
    ----------
    intent : dict
        TM Forum Intent.  Must contain ``parameters.codeReference.path``.
    logger : JobLogger
        Bound logger for this job.

    Returns
    -------
    dict
        ``{status, assessment_type, tool, facts, raw}`` — the canonical facts
        every audience rendition is projected from, beside the unmodified Bandit
        output they were derived from.
    """
    # Extract the target path from the intent parameters.
    target = intent.get("parameters", {}).get("codeReference", {}).get("path")
    logger.info(
        "skill.bandit",
        "[Skill Execution]\n"
        "Starting Bandit static code analysis\n"
        f"target={target}",
    )

    result = run_bandit_assessment(intent, logger)

    if result.get("status") == "FAILED":
        logger.error("skill.bandit", result.get("error", "Bandit assessment failed"))
        return result

    logger.info("skill.bandit", result.get("explanation", "Bandit assessment completed"))

    # Normalise before the result leaves the skill.  Deriving the findings here
    # rather than leaving Bandit's output for the report-composing model to read
    # is what keeps every audience rendition traceable to the same findings — and
    # it is where the credential values Bandit reports in cleartext are masked,
    # so they never enter the stored facts.
    facts = normalize(result, intent=intent)
    return normalised_result(
        facts,
        raw_result=result,
        assessment_type="static_code_analysis",
        tool="Bandit",
        logger=logger,
        component="skill.bandit",
    )


# The SKILL constant is discovered automatically by load_skills().
# The docs_content field is intentionally left empty here — load_skills()
# fills it in from docs/skills/bandit-static-code.md at startup.
SKILL = AssessmentSkill(
    name="bandit-static-code",
    description="Runs Bandit against Python source code and returns a vulnerability report.",
    assessment_types=[
        "static_code_analysis",
        "python_security",
        "code_vulnerability",
        "bandit",
    ],
    accepted_parameters=["codeReference"],
    execute=execute,
)
