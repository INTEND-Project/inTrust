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
from tools.bandit_assessment import run_bandit_assessment


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
        Assessment result with severity counts, verdict, explanation, and
        recommendations.
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
    else:
        logger.info("skill.bandit", result.get("explanation", "Bandit assessment completed"))

    return result


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
