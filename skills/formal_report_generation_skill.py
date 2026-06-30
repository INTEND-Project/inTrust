"""
Formal TM Forum report generation skill.

This skill turns a raw assessment result into the ontology vocabulary needed
to compose a TM Forum-aligned assessment report (tmfIntentReport.v1).  It does
**not** run an assessment — it only returns the InTrust ontology report
classes/properties together with the intent and raw result.

The orchestrator's tool wrapper passes a single string argument
(``reportInput``).  Because report generation needs both the original intent
and the raw assessment result, that string is expected to be a JSON object of
the form ``{"intent": {...}, "raw_result": {...}, "report_class": "..."}``.

See also: docs/skills/formal-report-generation.md
"""

import json
from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from tools.formal_report_generation import build_formal_report


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    """
    Build the ontology schema for shaping a raw assessment result into a report.

    Parameters
    ----------
    intent : dict
        Reconstructed intent.  ``parameters.reportInput`` holds a JSON object
        with ``intent`` and ``raw_result`` (and optionally ``report_class``).
    logger : JobLogger
        Bound logger for this job.

    Returns
    -------
    dict
        The ontology report fragments and instructions for composing a TMF
        report, or a FAILED result if the input could not be parsed.
    """
    raw = intent.get("parameters", {}).get("reportInput")

    if isinstance(raw, dict):
        report_request: Dict[str, Any] = raw
    elif isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {
                "status": "FAILED",
                "error": (
                    "report generation expects a JSON object with 'intent' and "
                    "'raw_result'; received a non-JSON string"
                ),
            }
        report_request = parsed if isinstance(parsed, dict) else {}
    else:
        report_request = {}

    logger.info(
        "skill.formal_report_generation",
        "[Skill Execution]\n"
        "Building formal TM Forum report vocabulary",
    )

    result = build_formal_report(report_request)

    if result.get("status") == "FAILED":
        logger.error(
            "skill.formal_report_generation",
            result.get("error", "Formal report generation failed"),
        )
    else:
        logger.info(
            "skill.formal_report_generation",
            "Formal report vocabulary returned; agent should now compose and "
            "validate the report.",
        )

    return result


SKILL = AssessmentSkill(
    name="formal-report-generation",
    description=(
        "Generates the InTrust ontology vocabulary needed to compose a formal "
        "TM Forum assessment report (tmfIntentReport.v1) from a raw result."
    ),
    assessment_types=[
        "report_generation",
        "formal_report",
        "tmf_report",
        "ontology_authoring",
    ],
    accepted_parameters=["reportInput"],
    execute=execute,
)
