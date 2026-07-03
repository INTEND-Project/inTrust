"""
Architecture A — multi-agent orchestration.

One root orchestrator ``LlmAgent`` owns NO tools itself; instead it has one
downstream specialist ``LlmAgent`` per assessment.  Each specialist owns:

- its own LLM instance (a separate ``LiteLlm`` object, even when the model
  name is the same — a stated property of this architecture),
- its own instruction (prompt/context),
- exactly one assessment tool.

ADK implements delegation automatically: because the root agent has
``sub_agents``, ADK injects a ``transfer_to_agent`` function into the root's
LLM request.  The root model reads each sub-agent's ``description`` (which
carries the same skill documentation that Architecture B carries in tool
docstrings — prompt parity) and transfers control to the chosen specialist.
The specialist then calls its tool and produces the final answer itself
(``disallow_transfer_to_parent=True``), the canonical "delegate and answer"
ADK pattern.

Structure of one run:  user intent -> root LLM (routing decision, 1 call)
-> specialist LLM (tool call decision, 1 call) -> tool executes ->
specialist LLM summarises (1 call).  That is 3 LLM invocations per run,
versus 2 in Architecture B — an inherent cost of the multi-agent style and
one of the properties the experiments measure.
"""

from typing import List

from google.adk.agents import LlmAgent

from orchestrator.skill_loader import AssessmentSkill, SkillRegistry

from .config import BenchmarkConfig
from .instrumentation import RunCollector, SilentLogger, make_timed_skill
from .model_factory import make_model
from .prompts import ORCHESTRATOR_INSTRUCTION, SPECIALIST_INSTRUCTION_TEMPLATE


def build_multi_agent(
    skills: List[AssessmentSkill],
    model_string: str,
    cfg: BenchmarkConfig,
    collector: RunCollector,
) -> LlmAgent:
    """
    Build the multi-agent orchestrator (root + specialists) for one run.

    Parameters mirror ``arch_single.build_single_agent`` exactly, so the
    benchmark runner can treat both architectures identically.
    """
    specialists = []
    for skill in skills:
        timed = make_timed_skill(skill, collector)

        # Reuse the production FunctionTool machinery for the specialist's
        # single tool (one-skill registry -> one tool).  This guarantees the
        # tool implementation and schema are IDENTICAL to Architecture B.
        registry = SkillRegistry([timed])
        (tool,) = registry.to_adk_tools(intent_id="benchmark", logger=SilentLogger())

        # The description is what the ROOT model reads when deciding which
        # specialist to transfer to.  It carries the same text that the tool
        # docstring carries in Architecture B (skill description + Markdown
        # docs), so both architectures receive identical routing information.
        description = f"{skill.description}\n\n{skill.docs_content}"

        specialists.append(
            LlmAgent(
                name=f"{skill.name.replace('-', '_')}_agent",
                # Each specialist gets its OWN model instance (fresh LiteLlm
                # object per make_model call) — isolated LLM per agent.
                model=make_model(model_string, cfg),
                instruction=SPECIALIST_INSTRUCTION_TEMPLATE.format(
                    skill_name=skill.name,
                    skill_description=skill.description,
                ),
                description=description,
                tools=[tool],
                # Specialists answer directly instead of handing control back
                # or sideways: keeps every run's structure deterministic
                # (root -> specialist -> final answer).
                disallow_transfer_to_parent=True,
                disallow_transfer_to_peers=True,
            )
        )

    return LlmAgent(
        name="orchestrator",
        model=make_model(model_string, cfg),
        instruction=ORCHESTRATOR_INSTRUCTION,
        description="InTrust assessment orchestrator (multi-agent architecture).",
        # No tools on the root: routing happens purely via transfer_to_agent,
        # which ADK injects automatically because sub_agents is non-empty.
        sub_agents=specialists,
    )
