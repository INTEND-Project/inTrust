"""
Architecture B — single agent + dynamically loaded skills.

One orchestrator ``LlmAgent`` receives ALL assessment skills as ADK
``FunctionTool``s and selects among them in a single shared LLM context.
This is exactly what the production InTrust service does
(``orchestrator/agent.py``), with two benchmark-specific differences:

- the LLM is a locally hosted Ollama model instead of Gemini, and
- each skill's execute function is wrapped with the timing instrumentation.

Structure of one run:  user intent -> orchestrator LLM (reads all tool
docstrings, picks one, extracts the target) -> tool executes -> orchestrator
LLM summarises the result.  That is 2 LLM invocations per run.
"""

from typing import List

from google.adk.agents import LlmAgent

from orchestrator.skill_loader import (
    AssessmentSkill,
    NullLogger,
    SkillRegistry,
)

from .config import BenchmarkConfig
from .instrumentation import RunCollector, make_timed_skill
from .model_factory import make_model
from .prompts import ORCHESTRATOR_INSTRUCTION


def build_single_agent(
    skills: List[AssessmentSkill],
    model_string: str,
    cfg: BenchmarkConfig,
    collector: RunCollector,
) -> LlmAgent:
    """
    Build the single-agent (skills) orchestrator for one benchmark run.

    Parameters
    ----------
    skills : list of AssessmentSkill
        The production skills (from ``load_skills()``), un-instrumented.
    model_string : str
        Model identifier from the config, e.g. "ollama_chat/qwen3:8b".
    cfg : BenchmarkConfig
        Provides provider settings.
    collector : RunCollector
        Per-run collector that the timed tool wrappers write into.

    Returns
    -------
    LlmAgent
        A fresh agent; the caller runs it with a fresh session so no
        conversation history leaks between runs.
    """
    # Wrap every skill with the timing instrumentation, then reuse the
    # production SkillRegistry/FunctionTool machinery unchanged — this keeps
    # Architecture B faithful to the production implementation.
    timed_skills = [make_timed_skill(skill, collector) for skill in skills]
    registry = SkillRegistry(timed_skills)
    tools = registry.to_adk_tools(intent_id="benchmark", logger=NullLogger())

    return LlmAgent(
        name="orchestrator",
        model=make_model(model_string, cfg),
        instruction=ORCHESTRATOR_INSTRUCTION,
        description="InTrust assessment orchestrator (single-agent architecture).",
        tools=tools,
    )
