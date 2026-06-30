"""
Formal TM Forum intent validation skill.

This skill validates a TM Forum intent against the InTrust SHACL shapes and
returns a structured conformance report.  It does **not** run an assessment.

The orchestrator's tool wrapper passes a single string argument (``intent``).
That string is either a JSON intent document or a Turtle (RDF) serialization;
this skill detects which and routes it to the backing validator accordingly.

See also: docs/skills/formal-intent-validation.md
"""

import json
from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from tools.formal_intent_validation import validate_formal_intent


def _build_payload(raw: Any) -> Dict[str, Any]:
    """Map the single string argument onto the validator's payload shape."""
    if isinstance(raw, dict):
        # Already a dict: treat as the intent JSON itself.
        return {"intent": raw}
    if not isinstance(raw, str):
        return {"intent": raw}

    stripped = raw.strip()
    # JSON object → intent; anything else → assume Turtle.
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return {"intent_ttl": raw}
        # Allow callers to pass the full payload ({"intent": ..., "context": ...})
        # or just the bare intent object.
        if isinstance(parsed, dict) and ("intent" in parsed or "intent_ttl" in parsed):
            return parsed
        return {"intent": parsed}
    return {"intent_ttl": raw}


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    """
    Validate the intent (JSON or Turtle) against the InTrust SHACL shapes.

    Parameters
    ----------
    intent : dict
        Reconstructed intent.  ``parameters.intent`` holds the intent to
        validate, as a JSON string/object or a Turtle string.
    logger : JobLogger
        Bound logger for this job.

    Returns
    -------
    dict
        Conformance report with ``conforms``, ``violation_count``, and
        ``violations``.
    """
    raw = intent.get("parameters", {}).get("intent")
    payload = _build_payload(raw)

    logger.info(
        "skill.formal_intent_validation",
        "[Skill Execution]\n"
        "Validating TM Forum intent against InTrust SHACL shapes",
    )

    result = validate_formal_intent(payload)

    if result.get("status") == "FAILED":
        logger.error(
            "skill.formal_intent_validation",
            result.get("error", "Formal intent validation failed"),
        )
    else:
        logger.info(
            "skill.formal_intent_validation",
            f"Validation complete: conforms={result.get('conforms')} "
            f"violations={result.get('violation_count')}",
        )

    return result


SKILL = AssessmentSkill(
    name="formal-intent-validation",
    description=(
        "Validates a TM Forum intent against the InTrust SHACL shapes and "
        "returns conformance violations."
    ),
    assessment_types=[
        "intent_validation",
        "shacl_validation",
        "formal_intent",
        "tmf_intent",
    ],
    accepted_parameters=["intent"],
    execute=execute,
)
