from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from tools.bandit_assessment import run_bandit_assessment


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
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
