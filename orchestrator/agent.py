"""
InTrust Runtime Orchestrator.

The ``RuntimeOrchestrator`` is the central coordinator of InTrust.  It
receives a raw assessment request (a TM Forum Intent dictionary or a
natural-language string), delegates skill selection to the ``SkillRegistry``
(which calls the LLM), executes the chosen skill, and wraps the result in a
standardised TM Forum-aligned output envelope.

There is intentionally only one orchestrator class.  All variability lives in
the skills — the orchestrator logic itself never needs to change when new
skills are added.
"""

from typing import Any, Dict

from .skill_loader import AssessmentSkill, SkillRegistry


# The agent name is embedded in every result's provenance section so that
# downstream consumers can identify which component produced the assessment.
AGENT_NAME = "InTrustRuntimeOrchestrator"

# Statuses returned by skill tools that indicate a successful run.
# The orchestrator maps these to the TM Forum lifecycle value "completed".
_SUCCESS_STATUSES = {"SUCCESS", "COMPLETED"}


class RuntimeOrchestrator:
    """
    Coordinates skill selection and execution for a single assessment request.

    Usage
    -----
    1. Instantiate with a populated ``SkillRegistry``.
    2. Call ``execute(intent, logger)`` to run the full assessment pipeline.
    3. The returned dictionary is a TM Forum-aligned report ready for storage
       and delivery to the caller.
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry
        self.agent_name = AGENT_NAME

    def select_skill(self, intent: Any) -> AssessmentSkill:
        """
        Ask the LLM which skill should handle ``intent``.

        Delegates entirely to ``SkillRegistry.select()``, which builds the
        LLM prompt, calls Gemini, and returns the chosen skill.

        Raises ``ValueError`` if no suitable skill is found (propagated from
        the registry so the executor can store a clean error message).
        """
        return self.registry.select(intent)

    def execute(self, intent: Any, logger: Any) -> Dict[str, Any]:
        """
        Run the full assessment pipeline for ``intent``.

        Steps:
        1. Ask the LLM to select the best skill.
        2. Log the selection decision.
        3. Invoke the skill's execute() function.
        4. Wrap the result in a standardised output envelope.

        Parameters
        ----------
        intent : dict or str
            The raw incoming request.  May be a TM Forum Intent dictionary
            or a plain natural-language string.
        logger : JobLogger
            Logger bound to the current job; writes to console and database.

        Returns
        -------
        dict
            A TM Forum-aligned assessment report (see ``_standardize_report``).
        """
        skill = self.select_skill(intent)

        # Log which skill was chosen so the decision is visible in the job
        # execution log and queryable via the /logs endpoint.
        logger.info(
            "orchestrator",
            f"[Orchestrator] LLM selected skill: {skill.name}\n"
            f"Description: {skill.description}",
        )

        result = skill.execute(intent, logger)
        return self._standardize_report(intent, skill, result)

    def _standardize_report(
        self,
        intent: Any,
        skill: AssessmentSkill,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Wrap the skill's raw result in a TM Forum-aligned envelope.

        TM Forum intents are expected to receive a structured response that
        includes lifecycle status, provenance (which agent/skill/tool ran),
        and the assessment findings.  This method produces that envelope
        consistently regardless of which skill ran.

        The ``lifecycleStatus`` field uses TM Forum conventions:
        - ``"completed"`` — the skill ran and produced a result (even if the
          target was found to be insecure; that is a finding, not a failure).
        - ``"failed"`` — the skill itself encountered an error (e.g. tool not
          found, network timeout, invalid parameters).

        Parameters
        ----------
        intent : dict or str
            The original incoming request, used to extract the intent ID.
        skill : AssessmentSkill
            The skill that was executed.
        result : dict
            The raw dictionary returned by the skill's execute() function.

        Returns
        -------
        dict
            Standardised report ready for storage and API response.
        """
        # Extract the intent ID from whichever field the caller used.
        # TM Forum allows both "intentId" and "id"; we also tolerate missing IDs.
        if isinstance(intent, dict):
            intent_id = intent.get("intentId") or intent.get("id") or "unknown"
            parameters = intent.get("parameters", {})
            assessment_type = (
                parameters.get("assessmentType")
                or intent.get("assessmentType")
                or intent.get("type")
            )
        else:
            # Natural-language request — no structured fields available.
            intent_id = "unknown"
            parameters = {}
            assessment_type = result.get("assessment_type")

        # Map the skill's status string to a TM Forum lifecycle value.
        raw_status = result.get("status", "")
        lifecycle_status = "completed" if raw_status in _SUCCESS_STATUSES else "failed"

        return {
            "intentId": intent_id,
            "lifecycleStatus": lifecycle_status,
            "assessmentType": result.get("assessment_type") or assessment_type,
            "skill": skill.name,
            "parameters": parameters,
            # "metrics" holds quantitative findings (e.g. vulnerability counts).
            # Skills may return this under different key names.
            "metrics": result.get("metrics") or result.get("issue_summary") or {},
            # "provenance" records exactly what ran so results are reproducible.
            "provenance": {
                "agent": self.agent_name,
                "skill": skill.name,
                "tool": result.get("tool"),
                "toolVersion": result.get("version"),
            },
            # The full raw result is preserved for downstream consumers that
            # need the complete tool output.
            "result": result,
            "explanation": result.get("explanation"),
            "recommendations": result.get("recommendations"),
        }
