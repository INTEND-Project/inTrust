"""
Formal TM Forum report validation skill.

This skill validates a TM Forum assessment report against the InTrust SHACL
shapes and returns a structured conformance report.  It does **not** run an
assessment.

The orchestrator's tool wrapper passes a single string argument (``report``).
That string is either a JSON report document or a Turtle (RDF) serialization;
this skill detects which and routes it to the backing validator accordingly.

See also: docs/skills/formal-report-validation.md
"""

import json
from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from tools.formal_report_validation import validate_formal_report


def _build_payload(raw: Any) -> Dict[str, Any]:
    """Map the single string argument onto the validator's payload shape."""
    if isinstance(raw, dict):
        return {"report": raw}
    if not isinstance(raw, str):
        return {"report": raw}

    stripped = raw.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return {"report_ttl": raw}
        if isinstance(parsed, dict) and ("report" in parsed or "report_ttl" in parsed):
            return parsed
        return {"report": parsed}
    return {"report_ttl": raw}


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    """
    Validate the report (JSON or Turtle) against the InTrust SHACL shapes.

    Parameters
    ----------
    intent : dict
        Reconstructed intent.  ``parameters.report`` holds the report to
        validate, as a JSON string/object or a Turtle string.
    logger : JobLogger
        Bound logger for this job.

    Returns
    -------
    dict
        Conformance report with ``conforms``, ``violation_count``, and
        ``violations``.
    """
    raw = intent.get("parameters", {}).get("report")
    payload = _build_payload(raw)

    logger.info(
        "skill.formal_report_validation",
        "[Skill Execution]\n"
        "Validating TM Forum report against InTrust SHACL shapes",
    )

    result = validate_formal_report(payload)

    if result.get("status") == "FAILED":
        logger.error(
            "skill.formal_report_validation",
            result.get("error", "Formal report validation failed"),
        )
    else:
        logger.info(
            "skill.formal_report_validation",
            f"Validation complete: conforms={result.get('conforms')} "
            f"violations={result.get('violation_count')}",
        )

    return result


SKILL = AssessmentSkill(
    name="formal-report-validation",
    description=(
        "Validates a TM Forum assessment report against the InTrust SHACL "
        "shapes and returns conformance violations."
    ),
    assessment_types=[
        "report_validation",
        "shacl_validation",
        "formal_report",
        "tmf_report",
    ],
    accepted_parameters=["report"],
    execute=execute,
)
