# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Membership Inference Attack (MIA) privacy assessment skill.

This skill evaluates how resilient a machine learning model is against
membership inference attacks by delegating the assessment to the remote MIA service
service.  Use it when the request asks whether a model leaks training-set
membership information, needs privacy auditing, or mentions membership
inference attacks.

The intent should provide the model reference under ``parameters.model`` and
the shadow data under ``parameters.shadowData``.

See also: docs/skills/mia-privacy.md
"""

from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from tools.mia_assessment import run_mia_assessment
from tools.mia_normalizer import normalize


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    """
    Run a membership inference assessment for the model specified in the intent.

    Parameters
    ----------
    intent : dict
        TM Forum Intent.  Expected to contain ``parameters.model`` and
        ``parameters.shadowData``.
    logger : JobLogger
        Bound logger for this job.

    Returns
    -------
    dict
        Assessment result retrieved from the MIA service, or a failure dict.
    """
    model = intent.get("parameters", {}).get("model")
    logger.info(
        "skill.mia",
        "[Skill Execution]\n"
        "Starting membership inference privacy assessment\n"
        f"model={model}",
    )

    result = run_mia_assessment(intent, logger)

    if isinstance(result, dict) and result.get("status") == "FAILED":
        logger.error("skill.mia", result.get("error", "MIA assessment failed"))
        return result

    logger.info("skill.mia", "MIA assessment completed")

    # Normalise the MIA sweep table into the canonical fact model before the
    # result leaves the skill.  Parsing the numbers here — rather than leaving
    # the table for the report-composing LLM to interpret — is what keeps every
    # audience-specific rendition traceable to the same figures, and is what
    # surfaces the worst configuration instead of the sweep's central tendency.
    facts = normalize(result, intent=intent)
    logger.info(
        "skill.mia",
        f"[Normalization] shape={facts.shape} "
        f"observations={len(facts.observations)} "
        f"findings={len(facts.findings)} "
        f"worstSeverity={facts.worst_severity}",
    )
    if facts.normalization_error:
        logger.warning(
            "skill.mia",
            f"[Normalization] partial result: {facts.normalization_error}",
        )

    # The raw MIA payload is retained under ``raw`` so the report can cite it
    # as evidence and a reader can re-derive every figure independently.
    #
    # ``version`` is forwarded from the tool envelope because the orchestrator
    # reads ``result["version"]`` for the report's ``provenance.toolVersion``.
    # Dropping it here is what left that field empty, which the composing LLM
    # then filled with an invented MIA version.
    return {
        "status": facts.status,
        "assessment_type": "membership_inference",
        "tool": "MIA service",
        "version": result.get("version") if isinstance(result, dict) else None,
        "facts": facts.to_dict(),
        "raw": result,
    }


# The SKILL constant is discovered automatically by load_skills().
# The docs_content field is intentionally left empty here — load_skills()
# fills it in from docs/skills/mia-privacy.md at startup.
SKILL = AssessmentSkill(
    name="mia-privacy",
    description=(
        "Evaluates a machine learning model's privacy resilience against "
        "membership inference attacks via the MIA service."
    ),
    assessment_types=[
        "privacy_assessment",
        "membership_inference",
        "model_privacy",
        "mia",
    ],
    # ``intentId`` is accepted so the LLM forwards the intent's id to the tool.
    # This matters in the ``adk web`` path, where the orchestrator's closure id
    # is fixed to "interactive" and cannot know the real intent id otherwise;
    # The MIA service is queried by intent id, so it must come from the intent itself.
    accepted_parameters=["intentId", "model", "shadowData"],
    execute=execute,
)
