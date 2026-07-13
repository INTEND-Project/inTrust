"""
Single-run executor: build a fresh agent, run one intent through it, and
extract all per-run metrics from the ADK event stream.

Methodology notes
-----------------
- Every run gets a FRESH agent, a FRESH ``InMemorySessionService`` and a
  FRESH session: no conversation history is ever reused between runs
  (requirement: each benchmark execution starts from a clean LLM session).
- End-to-end latency is measured with ``time.perf_counter()`` around the
  complete event stream (request -> LLM reasoning -> tool execution ->
  response generation).
- The internal timeline is reconstructed from ADK ``Event.timestamp`` values
  (wall clock), aligned against a ``time.time()`` stamp taken at request
  submission.  Tool execution time comes from the timing wrapper in
  ``instrumentation.py`` (authoritative — measured around the subprocess
  itself, without event-delivery latency).
- Token usage is read from ``event.usage_metadata`` when the backend
  provides it (LiteLLM/Ollama does); if absent the run records ``None``
  and the report shows "N/A".  Missing token statistics NEVER fail a run.
"""

import asyncio
import json
import time
import uuid
from typing import List, Optional

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from orchestrator.skill_loader import AssessmentSkill

from .arch_multi import build_multi_agent
from .arch_single import build_single_agent
from .config import BenchmarkConfig
from . import routing_analysis
from .instrumentation import RunCollector
from .metrics import RunResult
from .scenarios import Scenario

# ADK app name used for all benchmark sessions.
_APP_NAME = "intrust-benchmark"
_USER_ID = "benchmark"

# Name of the delegation function ADK injects for multi-agent routing.
_TRANSFER_FN = "transfer_to_agent"

# Tool result statuses that count as a successful assessment (matches the
# production convention in orchestrator/agent.py).
_TOOL_SUCCESS_STATUSES = {"SUCCESS", "COMPLETED"}


async def execute_run(
    architecture: str,
    model_string: str,
    scenario: Scenario,
    skills: List[AssessmentSkill],
    cfg: BenchmarkConfig,
    run_idx: int,
    concurrency: int = 1,
    warmup: bool = False,
) -> RunResult:
    """
    Execute one benchmark run and return its RunResult.

    All exceptions (model unreachable, timeout, tool crash) are caught and
    recorded as a FAILED run so long experiment campaigns never abort.
    """
    # Rotate through the scenario's frozen intent variants so a measured
    # cell samples several distinct intent formulations (see scenarios.py).
    intent_variant = run_idx % len(scenario.intents)
    intent = scenario.intents[intent_variant]

    result = RunResult(
        architecture=architecture,
        model=model_string,
        scenario=scenario.name,
        concurrency=concurrency,
        run_idx=run_idx,
        intent_variant=intent_variant,
        warmup=warmup,
        expected=(
            scenario.expected_agent
            if architecture == "multi_agent"
            else scenario.expected_tool_fn
        ),
    )

    # ---- build a fresh agent for this run -----------------------------------
    collector = RunCollector()
    if architecture == "single_agent":
        agent = build_single_agent(skills, model_string, cfg, collector)
    elif architecture == "multi_agent":
        agent = build_multi_agent(skills, model_string, cfg, collector)
    else:
        raise ValueError(f"Unknown architecture: {architecture!r}")

    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name=_APP_NAME, session_service=session_service)
    session_id = f"{scenario.name}-{uuid.uuid4().hex[:8]}"
    await session_service.create_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=session_id
    )

    # The intent is sent exactly as stored — identical input for both
    # architectures and all models.
    user_message = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=json.dumps(intent, indent=2))],
    )

    # ---- run and consume the event stream ------------------------------------
    # wall_start aligns ADK event timestamps (wall clock) with the run start;
    # perf_start measures the authoritative end-to-end duration.
    wall_start = time.time()
    perf_start = time.perf_counter()

    selection_ts: Optional[float] = None
    last_fn_response_ts: Optional[float] = None
    final_ts: Optional[float] = None
    prompt_tokens = completion_tokens = total_tokens = 0
    saw_token_data = False

    async def _consume() -> None:
        nonlocal selection_ts, last_fn_response_ts, final_ts
        nonlocal prompt_tokens, completion_tokens, total_tokens, saw_token_data

        async for event in runner.run_async(
            user_id=_USER_ID, session_id=session_id, new_message=user_message
        ):
            # -- routing detection --------------------------------------------
            for fn_call in event.get_function_calls():
                if fn_call.name == _TRANSFER_FN:
                    # Multi-agent: the root decided which specialist gets the
                    # request.  The agent name is in the call arguments.
                    if result.selected is None:
                        result.selected = (fn_call.args or {}).get("agent_name")
                        selection_ts = event.timestamp
                elif result.selected is None and architecture == "single_agent":
                    # Single-agent: the first (non-transfer) tool call IS the
                    # skill selection.
                    result.selected = fn_call.name
                    selection_ts = event.timestamp
                result.timeline.append(
                    {"t": event.timestamp, "author": event.author,
                     "kind": "function_call", "name": fn_call.name}
                )

            for fn_response in event.get_function_responses():
                last_fn_response_ts = event.timestamp
                result.timeline.append(
                    {"t": event.timestamp, "author": event.author,
                     "kind": "function_response", "name": fn_response.name}
                )

            # -- token accounting ----------------------------------------------
            usage = getattr(event, "usage_metadata", None)
            if usage is not None:
                saw_token_data = True
                prompt_tokens += usage.prompt_token_count or 0
                completion_tokens += usage.candidates_token_count or 0
                total_tokens += usage.total_token_count or 0

            # -- final response -------------------------------------------------
            if event.is_final_response() and event.content:
                final_ts = event.timestamp
                for part in event.content.parts or []:
                    if getattr(part, "text", None):
                        result.final_text = part.text
                result.timeline.append(
                    {"t": event.timestamp, "author": event.author,
                     "kind": "final_response", "name": None}
                )

    try:
        await asyncio.wait_for(_consume(), timeout=cfg.run_timeout_sec)
    except Exception as exc:  # timeout, connection error, tool crash, ...
        result.status = "FAILED"
        result.error = f"{type(exc).__name__}: {exc}"

    # Status refinement depends on whether a skill was SUPPOSED to run.
    if result.status == "OK" and scenario.is_supported:
        # A tool that ran but reported failure (e.g. bad arguments from the
        # LLM) fails the run — the assessment did not actually happen.
        failed_tools = [c for c in collector.tool_calls
                        if c["status"] not in _TOOL_SUCCESS_STATUSES]
        if failed_tools:
            result.status = "FAILED"
            result.error = (f"tool '{failed_tools[0]['skill']}' reported "
                            f"{failed_tools[0]['status']}: "
                            f"{failed_tools[0].get('error')}")
        elif not collector.tool_calls:
            # The model answered without executing any assessment tool.
            result.status = "FAILED"
            result.error = "no assessment tool was executed"
    # For a gatekeeping (unsupported) scenario neither branch applies:
    # calling no tool is the CORRECT outcome, and even a wrongly-invoked
    # tool leaves the run completed — the decision quality is measured by
    # routing_correct below, not by run status.

    # ---- derive the metrics ----------------------------------------------------
    result.e2e_ms = (time.perf_counter() - perf_start) * 1000.0

    if selection_ts is not None:
        result.selection_ms = (selection_ts - wall_start) * 1000.0

    result.tool_ms = collector.total_tool_time_sec * 1000.0
    # llm_ms = everything that is not tool execution: LLM reasoning for
    # routing, tool-call construction, and final-answer generation, plus
    # (small) ADK framework overhead.  Reported as one number because the
    # LLM server does not expose finer-grained timings.
    result.llm_ms = result.e2e_ms - result.tool_ms
    if final_ts is not None and last_fn_response_ts is not None:
        result.format_ms = (final_ts - last_fn_response_ts) * 1000.0

    if saw_token_data:
        result.prompt_tokens = prompt_tokens
        result.completion_tokens = completion_tokens
        result.total_tokens = total_tokens
    # else: leave as None -> reported as "N/A" downstream.

    # ---- routing accuracy --------------------------------------------------------
    if scenario.is_supported:
        # No selection at all (model never called a tool / never transferred)
        # is a routing failure, not a crash — one of the phenomena measured.
        result.routing_correct = (
            result.selected is not None and result.selected == result.expected
        )
    else:
        # Gatekeeping: the correct decision is to select NOTHING (the request
        # matches no available skill).  Any selection is over-triggering.
        result.routing_correct = result.selected is None

    # ---- routing decomposition (decision vs native-call adherence) ---------------
    intended, native_call, refused = routing_analysis.classify(
        result.selected, result.final_text)
    result.intended_skill = intended
    result.native_call = native_call
    result.decision_correct = routing_analysis.decision_correct(
        intended, native_call, refused,
        scenario.expected_skill, scenario.is_supported)

    return result
