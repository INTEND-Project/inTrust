"""
Formal TM Forum intent generation skill.

This skill turns a natural-language description of a desired trustworthiness
assessment into the ontology vocabulary needed to compose a formal TM Forum
intent JSON.  It does **not** run an assessment — it only returns the InTrust
ontology classes/properties (plus the echoed description) so the agent can
author a grounded intent in its next turn.

The orchestrator's tool wrapper passes a single string argument (``description``)
which is placed at ``parameters.description``.  The string may also be a JSON
object carrying the optional pass-through fields (requestedBy, targetHint,
criteria, dueBy) alongside the description.

See also: docs/skills/formal-intent-generation.md
"""

import json
from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from tools.formal_intent_generation import build_formal_intent


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    """
    Build the ontology schema for the natural-language description in the intent.

    Parameters
    ----------
    intent : dict
        Reconstructed intent.  ``parameters.description`` holds the user's
        natural-language description (or a JSON object with ``description`` and
        optional pass-through fields).
    logger : JobLogger
        Bound logger for this job.

    Returns
    -------
    dict
        The ontology fragments and instructions for composing a TMF intent.
    """
    raw = intent.get("parameters", {}).get("description")

    # The wrapper hands us one string.  Accept either a plain description or a
    # JSON object carrying description + optional pass-through fields.
    intent_request: Dict[str, Any]
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
                intent_request = parsed if isinstance(parsed, dict) else {"description": raw}
            except json.JSONDecodeError:
                intent_request = {"description": raw}
        else:
            intent_request = {"description": raw}
    elif isinstance(raw, dict):
        intent_request = raw
    else:
        intent_request = {"description": raw}

    logger.info(
        "skill.formal_intent_generation",
        "[Skill Execution]\n"
        "Building formal TM Forum intent vocabulary\n"
        f"description={intent_request.get('description')}",
    )

    result = build_formal_intent(intent_request)

    if result.get("status") == "FAILED":
        logger.error(
            "skill.formal_intent_generation",
            result.get("error", "Formal intent generation failed"),
        )
    else:
        logger.info(
            "skill.formal_intent_generation",
            "Formal intent vocabulary returned; agent should now compose and "
            "validate the intent.",
        )

    return result


SKILL = AssessmentSkill(
    name="formal-intent-generation",
    description=(
        "Generates the InTrust ontology vocabulary needed to compose a formal "
        "TM Forum intent JSON from a natural-language description."
    ),
    assessment_types=[
        "intent_generation",
        "formal_intent",
        "tmf_intent",
        "ontology_authoring",
    ],
    accepted_parameters=["description"],
    execute=execute,
)
