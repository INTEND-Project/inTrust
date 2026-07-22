"""
InTrust Runtime Orchestrator — powered by Google ADK.

This module provides two things:

1. ``root_agent`` — a module-level ADK ``LlmAgent`` instance.
   This is the entry point for the ``adk web`` chatbot interface.
   Running ``adk web`` in the project directory will discover this agent via
   the top-level ``agent.py`` file and launch the web UI.

2. ``RuntimeOrchestrator`` — a class that the FastAPI job executor uses to
   run assessments programmatically.  It creates a per-job agent with skill
   tools that are bound to the current job's logger, then uses the ADK
   ``Runner`` to drive the LLM → tool call → result flow.

How ADK skill selection works
-----------------------------
Instead of manually constructing a prompt and parsing the LLM's text response
(the previous approach), we register each skill as an ADK ``FunctionTool``.
The LLM agent reads the tool descriptions (which include the skill's Markdown
documentation) and decides autonomously which tool to call.  ADK handles the
full cycle: sending the request, receiving the tool call decision, executing
the function, feeding the result back to the model, and producing a final
response.

The caller (RuntimeOrchestrator) inspects the event stream to capture the
structured tool call result, then wraps it in a TM Forum-aligned report
envelope via ``_standardize_report()``.
"""

import asyncio
import json
from typing import Any, Dict, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google import genai
from google.genai import types as genai_types

from .skill_loader import AssessmentSkill, SkillRegistry, load_skills

# Deterministic post-processing tools invoked from _standardize_report.
from tools.formal_report_generation import build_formal_report
from tools.formal_report_validation import validate_formal_report


AGENT_NAME = "InTrustRuntimeOrchestrator"

# Statuses returned by skill tools that indicate a successful run.
_SUCCESS_STATUSES = {"SUCCESS", "COMPLETED"}

# System instruction given to the LLM agent.
# It explains what InTrust does and how the agent should behave.
_AGENT_INSTRUCTION = """\
You are the InTrust Runtime Orchestrator, an intelligent trustworthiness
assessment agent for the computing continuum.

Your job is to interpret an incoming assessment request (which may be a
structured TM Forum Intent in JSON format, or a plain natural-language
description of what the user wants assessed) and select the most appropriate
assessment skill to execute.

You have access to a set of assessment tools, each wrapping a specialised
security scanner.  Read each tool's description carefully and call the one
that best matches the request.  Pass the target identifier (file path, image
name, cluster name, etc.) extracted from the request to the tool.

If no tool is appropriate for the request, explain politely that InTrust does
not currently support the requested assessment type.

Always respond in a professional, concise manner.  When you have the tool
result, summarise the key findings for the user.
"""


def _build_root_agent() -> LlmAgent:
    """
    Build the root ADK agent for use with ``adk web`` and ``adk run``.

    Loads all skills from the skills/ directory and creates tool wrappers
    without a per-job logger (safe for interactive use — output goes to stdout
    rather than the database).

    This is called once at module import time.  If skills fail to load
    (e.g. a missing .md file), the error is raised immediately so the
    developer sees it at startup rather than at request time.
    """
    registry = load_skills()
    # Pass intent_id="interactive" and logger=None for the web chatbot context.
    tools = registry.to_adk_tools(intent_id="interactive", logger=None)
    return LlmAgent(
        name=AGENT_NAME,
        model="gemini-3.5-flash",
        instruction=_AGENT_INSTRUCTION,
        description=(
            "InTrust assessment orchestrator — interprets TM Forum intents and "
            "executes trustworthiness assessments using specialised skills."
        ),
        tools=tools,
    )


# Module-level agent instance used by ``adk web``.
# Imported by the top-level agent.py file that ADK discovers.
root_agent = _build_root_agent()


class RuntimeOrchestrator:
    """
    Drives the ADK agent for a single API assessment job.

    Each job creates a fresh ``LlmAgent`` with tools that close over the
    per-job logger.  This ensures log messages are attributed to the correct
    job in the database without using global state.

    Usage
    -----
    1. Instantiate with a populated ``SkillRegistry``.
    2. Call ``await execute_async(intent, logger)`` from the async executor.
    3. The returned dictionary is a TM Forum-aligned report ready for storage.
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry
        self.agent_name = AGENT_NAME

    async def execute_async(self, intent: Any, logger: Any) -> Dict[str, Any]:
        """
        Run the full assessment pipeline for ``intent`` using ADK.

        Steps:
        1. Build ADK FunctionTools for all skills, injecting the job logger.
        2. Create a per-job LlmAgent with those tools.
        3. Use ADK Runner to send the intent to the agent.
        4. Stream events to capture: which tool was called, and its result.
        5. Wrap the skill result in a TM Forum-aligned report envelope.

        Parameters
        ----------
        intent : dict or str
            The raw incoming request.  May be a TM Forum Intent dictionary
            or a plain natural-language string.
        logger : JobLogger
            Logger bound to the current job.

        Returns
        -------
        dict
            A TM Forum-aligned assessment report.

        Raises
        ------
        ValueError
            If the LLM agent did not call any skill tool (no suitable skill).
        """
        # Extract intent_id for the tool closures and the final report.
        if isinstance(intent, dict):
            intent_id = intent.get("intentId") or intent.get("id") or "unknown"
        else:
            intent_id = "unknown"

        # Build per-job tools with the logger injected via closure.
        tools = self.registry.to_adk_tools(intent_id=intent_id, logger=logger)

        # Create a short-lived agent for this job.
        # LlmAgent construction is cheap (no network call); the model is only
        # contacted when Runner.run_async() is called.
        job_agent = LlmAgent(
            name=self.agent_name,
            model="gemini-3.5-flash",
            instruction=_AGENT_INSTRUCTION,
            tools=tools,
        )

        session_service = InMemorySessionService()
        runner = Runner(
            agent=job_agent,
            app_name="intrust",
            session_service=session_service,
        )

        # Serialise the intent for the LLM.  Structured intents are sent as
        # JSON; natural-language strings are sent as-is.
        if isinstance(intent, dict):
            user_message_text = json.dumps(intent, indent=2)
        else:
            user_message_text = str(intent)

        user_message = genai_types.Content(
            role="user",
            parts=[genai_types.Part(text=user_message_text)],
        )

        # ADK requires the session to exist before run_async is called.
        # We use the intent_id as the session_id so execution history is
        # traceable, but must create it first.
        APP_NAME = "intrust"
        USER_ID = "intrust-api"
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=USER_ID,
            session_id=intent_id,
        )

        logger.info(
            "orchestrator",
            f"[Orchestrator] Submitting intent to ADK agent\n"
            f"intent_id={intent_id}",
        )

        # Stream events from the ADK runner and capture what we need.
        chosen_skill_name: Optional[str] = None
        skill_result: Optional[Dict[str, Any]] = None
        final_text: Optional[str] = None

        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=intent_id,
            new_message=user_message,
        ):
            # Capture which tool the model called (= which skill was selected).
            for fn_call in event.get_function_calls():
                if chosen_skill_name is None:
                    # Convert function name back to skill name
                    # (underscore → hyphen, as FunctionTool uses Python identifiers).
                    chosen_skill_name = fn_call.name.replace("_", "-")
                    logger.info(
                        "orchestrator",
                        f"[Orchestrator] LLM selected skill: {chosen_skill_name}",
                    )

            # Capture the tool's structured return value.
            for fn_response in event.get_function_responses():
                if skill_result is None and fn_response.response:
                    skill_result = fn_response.response

            # Capture the agent's final natural-language response text.
            if event.is_final_response() and event.content:
                for part in event.content.parts or []:
                    if getattr(part, "text", None):
                        final_text = part.text

        if skill_result is None:
            # The model did not call any tool — no suitable skill was found.
            raise ValueError(
                "The assessment agent did not select any skill for this request. "
                "InTrust currently supports Python static code analysis (Bandit) "
                "and filesystem, Docker image, and Kubernetes cluster scanning "
                "(Trivy).  Please revise your request."
            )

        logger.info(
            "orchestrator",
            f"[Orchestrator] Skill execution complete\n"
            f"skill={chosen_skill_name}\n"
            f"agent_summary={final_text or '(none)'}",
        )

        # Find the AssessmentSkill object so _standardize_report can include
        # its metadata in the report provenance section.
        skill_obj = self.registry.get(chosen_skill_name) if chosen_skill_name else None

        return await self._standardize_report(
            intent, skill_obj, skill_result, final_text, logger
        )

    def execute(self, intent: Any, logger: Any) -> Dict[str, Any]:
        """
        Synchronous wrapper around ``execute_async`` for compatibility.

        Used by ``_execute_with_captured_output`` in the executor, which runs
        this function inside ``asyncio.to_thread``.  Because the async runner
        needs an event loop, we create a new one here rather than reusing the
        main FastAPI loop (which would deadlock if called from a thread).
        """
        return asyncio.run(self.execute_async(intent, logger))

    async def _standardize_report(
        self,
        intent: Any,
        skill: Optional[AssessmentSkill],
        result: Dict[str, Any],
        agent_summary: Optional[str] = None,
        logger: Any = None,
    ) -> Dict[str, Any]:
        """
        Wrap the skill's raw result in a TM Forum-aligned envelope.

        The ``lifecycleStatus`` field uses TM Forum conventions:
        - ``"completed"`` — the skill ran (even if findings were detected).
        - ``"failed"`` — the skill itself encountered an error.

        The ``agent_summary`` field contains the LLM's natural-language
        interpretation of the result, useful for human-readable reporting.

         As a deterministic post-processing step, every report is also run
        through formal report *composition* (LLM-authored tmfIntentReport.v1)
        and SHACL *validation*.  This is wired in here — rather than as a
        chained skill — because the ADK event loop only captures the first
        tool call/result, so a follow-up report-generation skill would never
        reach this envelope.  Both sub-steps degrade gracefully: any failure
        is recorded in the report rather than raised, so report shaping never
        fails an otherwise-successful assessment.
        """
        if isinstance(intent, dict):
            intent_id = intent.get("intentId") or intent.get("id") or "unknown"
            parameters = intent.get("parameters", {})
            assessment_type = (
                parameters.get("assessmentType")
                or intent.get("assessmentType")
                or intent.get("type")
            )
        else:
            intent_id = "unknown"
            parameters = {}
            assessment_type = result.get("assessment_type")

        raw_status = str(result.get("status", ""))
        lifecycle_status = (
            "completed" if raw_status.upper() in _SUCCESS_STATUSES else "failed"
        )
        
        report = {
            "intentId": intent_id,
            "lifecycleStatus": lifecycle_status,
            "assessmentType": result.get("assessment_type") or assessment_type,
            "skill": skill.name if skill else "unknown",
            "parameters": parameters,
            "metrics": result.get("metrics") or result.get("issue_summary") or {},
            "provenance": {
                "agent": self.agent_name,
                "skill": skill.name if skill else "unknown",
                "tool": result.get("tool"),
                "toolVersion": result.get("version"),
            },
            "result": result,
            "explanation": result.get("explanation"),
            # Include the LLM's natural-language summary alongside the
            # structured explanation from the skill tool.
            "agentSummary": agent_summary,
            "recommendations": result.get("recommendations"),
        }

        # Deterministic post-processing: compose a formal TMF report from the
        # raw result and validate it against the InTrust SHACL shapes.  Never
        # raises — failures are attached to the report envelope instead.
        composed, validation = await self._compose_and_validate_report(
            intent, skill, result, logger
        )
        report["formalReport"] = composed
        report["formalReportValidation"] = validation

        return report

    async def _compose_and_validate_report(
        self,
        intent: Any,
        skill: Optional[AssessmentSkill],
        result: Dict[str, Any],
        logger: Any = None,
    ) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Compose a tmfIntentReport.v1 report and validate it via SHACL.

        Three stages, each isolated so a failure only nulls its own output:

        1. ``build_formal_report`` — deterministic ontology scaffold (classes,
           properties, composition instructions) from intent + raw result.
        2. Gateway LLM call — authors the actual TMF report JSON using that
           scaffold as the authoritative vocabulary.
        3. ``validate_formal_report`` — SHACL conformance check of the composed
           report against the InTrust shapes.

        Returns
        -------
        (composed_report, validation_result)
            ``composed_report`` is the parsed TMF JSON (or a ``{"status":
            "FAILED", "error": ...}`` dict when a stage fails).
            ``validation_result`` is the SHACL conformance report, or ``None``
            when there was no valid composed report to validate.
        """
        def _log_error(message: str) -> None:
            if logger is not None:
                logger.error("orchestrator.formal_report", message)

        # Stage 1 — deterministic scaffold.
        try:
            scaffold = build_formal_report({"intent": intent, "raw_result": result})
        except Exception as exc:  # noqa: BLE001
            _log_error(f"formal report scaffold error: {exc}")
            return {"status": "FAILED", "error": f"scaffold error: {exc}"}, None
        if scaffold.get("status") != "SUCCESS":
            _log_error(f"formal report scaffold failed: {scaffold.get('error')}")
            return scaffold, None

        # Stage 2 — LLM composes the TMF report JSON from the scaffold.
        prompt = (
            "You compose TM Forum assessment reports for the InTrust framework.\n"
            "Using ONLY the ontology vocabulary, the intent, the raw result and "
            "the instructions in the JSON below, produce a single "
            "tmfIntentReport.v1 report.\n"
            "Respond with the report as raw JSON only — no markdown fences, no "
            "commentary.\n\n"
            f"{json.dumps(scaffold, indent=2, default=str)}"
        )
        try:
            client = genai.Client()
            response = await client.aio.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
            )
            raw_text = response.text
            composed = self._parse_report_json(raw_text)
        except Exception as exc:  # noqa: BLE001
            _log_error(f"formal report composition error: {exc}")
            return {"status": "FAILED", "error": f"composition error: {exc}"}, None

        if composed is None:
            _log_error("formal report composition returned unparseable JSON")
            return {
                "status": "FAILED",
                "error": "LLM did not return valid JSON",
                "raw": raw_text,
            }, None

        # Deterministic backfill: the fields we already know authoritatively
        # (intentId, status, reportType) are not left to the LLM, which tends
        # to emit placeholders like "fill" or omit required fields entirely.
        composed = self._backfill_required_fields(composed, intent, skill, result)

        # Stage 3 — SHACL validation of the composed report.
        try:
            validation = validate_formal_report({"report": composed})
        except Exception as exc:  # noqa: BLE001
            _log_error(f"formal report validation error: {exc}")
            validation = {"status": "FAILED", "error": f"validation error: {exc}"}

        return composed, validation

    @staticmethod
    def _backfill_required_fields(
        composed: Dict[str, Any],
        intent: Any,
        skill: Optional[AssessmentSkill],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Overwrite the SHACL-required fields we know authoritatively.

        The composing LLM frequently emits placeholders (e.g. ``intentId:
        "fill"``) or omits ``reportType`` / ``status`` entirely, which fails the
        AssessmentReportShape MinCount constraints.  We own these three values,
        so we set them deterministically rather than trusting the model:

        - ``intentId``  — from the intent (never a placeholder).
        - ``status``    — from the raw result, normalised to the SHACL enum
          (``SUCCESS`` / ``FAILED`` / ``INCONCLUSIVE``).
        - ``reportType``— from the skill name, defaulting to a valid label when
          the model left it blank.

        These always overwrite the model's values for ``intentId`` and
        ``status`` (we are the source of truth); ``reportType`` is only filled
        when missing/blank so a sensible model-provided type is preserved.
        """
        if not isinstance(composed, dict):
            return composed

        # intentId — authoritative, always overwrite.
        if isinstance(intent, dict):
            intent_id = intent.get("intentId") or intent.get("id") or "unknown"
        else:
            intent_id = "unknown"
        composed["intentId"] = intent_id

        # status — normalise the raw tool status to the SHACL enum.
        raw_status = str(result.get("status", "")).upper()
        if raw_status in _SUCCESS_STATUSES:
            composed["status"] = "SUCCESS"
        elif raw_status in {"FAILED", "ERROR", "FAILURE"}:
            composed["status"] = "FAILED"
        else:
            composed["status"] = "INCONCLUSIVE"

        # reportType — fill only if the model omitted it.
        existing_type = composed.get("reportType")
        if not (isinstance(existing_type, str) and existing_type.strip()):
            skill_name = skill.name if skill else None
            if skill_name:
                # e.g. "mia-privacy" -> "MiaPrivacyAssessmentReport"
                camel = "".join(part.capitalize() for part in skill_name.split("-"))
                composed["reportType"] = f"{camel}AssessmentReport"
            else:
                composed["reportType"] = "AssessmentReport"

        return composed

    @staticmethod
    def _parse_report_json(text: str) -> Optional[Dict[str, Any]]:
        """
        Parse an LLM response into a report dict.

        Handles the common cases where the model wraps JSON in ```json fences
        or adds surrounding prose, by falling back to the outermost brace span.
        Returns ``None`` if nothing parseable is found.
        """
        if not text:
            return None
        candidate = text.strip()
        if candidate.startswith("```"):
            # Strip a leading ```json / ``` fence and the trailing ```.
            candidate = candidate.split("```", 2)[1] if "```" in candidate else candidate
            if candidate.lower().startswith("json"):
                candidate = candidate[4:]
            candidate = candidate.strip().rstrip("`").strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            start, end = candidate.find("{"), candidate.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                parsed = json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                return None
        return parsed if isinstance(parsed, dict) else None

