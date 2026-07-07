"""
Skill framework for InTrust.

This module defines the core building blocks of the skill system:

- ``AssessmentSkill``: a dataclass describing one assessment capability
  (e.g. Bandit static analysis, Trivy image scan).
- ``SkillRegistry``: a container that holds all loaded skills and can expose
  them as ADK FunctionTools for use by the LlmAgent.
- ``load_skills()``: a factory function that discovers and imports every
  ``*_skill.py`` file in the ``skills/`` directory and registers them.

Adding a new skill to the system requires only two things:
1. Create ``skills/<name>_skill.py`` that exposes a ``SKILL`` constant of
   type ``AssessmentSkill``.
2. Create ``docs/skills/<name>.md`` that describes the skill in plain
   English (this text is embedded in the LLM agent's tool descriptions
   so the model knows when to use the skill).
No changes to the orchestrator or any other file are needed.

IMPORTANT — skill documentation is read by the LLM as a tool description.
Never mention callable-looking identifiers in the .md files other than the
tool's own name: no internal function names (``run_bandit_assessment``),
no hyphenated skill names in frontmatter.  Models — especially smaller
ones — will obediently try to call whatever name the documentation shows
them, and fail because no such tool is registered.
"""

import importlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from google.adk.tools import FunctionTool


class NullLogger:
    """Fallback logger used when no job context is available (e.g. adk web)."""

    def info(self, component: str, message: str) -> None:
        print(f"[{component}] {message}")

    def warning(self, component: str, message: str) -> None:
        print(f"[WARNING][{component}] {message}")

    def error(self, component: str, message: str) -> None:
        print(f"[ERROR][{component}] {message}")

    def exception(self, component: str, message: str, exc: BaseException) -> None:
        print(f"[ERROR][{component}] {message}: {exc}")


# Type alias for the skill execution function signature.
# Every skill's execute() function receives the raw intent dictionary and a
# JobLogger instance, and returns a result dictionary.
SkillExecuteFn = Callable[[Dict[str, Any], Any], Dict[str, Any]]

# Path to the directory that contains per-skill Markdown description files.
# These files are read at startup and used to build tool descriptions for the
# LLM, so it understands when to invoke each skill.
_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs" / "skills"


@dataclass(frozen=True)
class AssessmentSkill:
    """
    Describes one assessment skill that InTrust can execute.

    Attributes
    ----------
    name : str
        Unique identifier for the skill (e.g. ``"bandit-static-code"``).
        Must match the stem of the corresponding ``docs/skills/<name>.md``
        file.
    description : str
        Short, one-sentence description shown in the ``/skills`` API endpoint.
    assessment_types : list of str
        Keywords that characterise this skill's domain (used for display
        and documentation).
    accepted_parameters : list of str
        Top-level keys inside the intent's ``parameters`` object that this
        skill expects (e.g. ``["codeReference"]``).
    execute : callable
        The function that performs the actual assessment.  Signature:
        ``execute(intent: dict, logger: JobLogger) -> dict``.
    docs_content : str
        Full text of the ``docs/skills/<name>.md`` file.  Loaded at startup
        by ``load_skills()`` and embedded in ADK tool descriptions so the
        model understands when to use this skill.  Skill files themselves do
        not need to set this — ``load_skills()`` fills it in automatically.
    """

    name: str
    description: str
    assessment_types: List[str]
    accepted_parameters: List[str]
    execute: SkillExecuteFn
    # Defaults to empty string so skill files can define SKILL without
    # specifying docs_content directly.  load_skills() always overwrites this.
    docs_content: str = ""


class SkillRegistry:
    """
    Holds all registered skills and exposes them as ADK FunctionTools.

    The registry is populated once at startup by ``load_skills()`` and then
    passed to the ``RuntimeOrchestrator``.  The orchestrator uses
    ``to_adk_tools()`` to get callable tool wrappers for the LLM agent.
    """

    def __init__(self, skills: List[AssessmentSkill]) -> None:
        # Store skills in a dict keyed by name for O(1) lookup.
        self._skills: Dict[str, AssessmentSkill] = {
            skill.name: skill for skill in skills
        }

    def list(self) -> List[AssessmentSkill]:
        """Return all registered skills."""
        return list(self._skills.values())

    def get(self, name: str) -> Optional[AssessmentSkill]:
        """Return a skill by its exact name, or ``None`` if not found."""
        return self._skills.get(name)

    def to_adk_tools(
        self,
        intent_id: str,
        logger: Any = None,
    ) -> List[FunctionTool]:
        """
        Build a list of ADK FunctionTool objects from the registered skills.

        Each tool wraps one skill's execute function.  The ``intent_id`` and
        ``logger`` are captured in the closure so the tool can reconstruct the
        minimal intent dict and route log messages to the correct job.

        When called from the ``adk web`` chatbot (where no job exists and no
        logger is available), pass ``logger=None`` — the tools will still run
        but will not write to the job database.

        Parameters
        ----------
        intent_id : str
            The intent/job identifier to embed in the skill's result.
        logger : JobLogger, optional
            Bound logger for this job.  ``None`` is safe (disables DB logging).

        Returns
        -------
        list of FunctionTool
            One ADK tool per registered skill, ready to pass to an LlmAgent.
        """
        tools = []
        for skill in self.list():
            tools.append(_make_skill_tool(skill, intent_id, logger))
        return tools


def _make_skill_tool(
    skill: AssessmentSkill,
    intent_id: str,
    logger: Any,
) -> FunctionTool:
    """
    Create an ADK FunctionTool that wraps a single assessment skill.

    The returned function's docstring is what the LLM reads to decide whether
    to call this tool.  It combines the skill's description with the full
    content of its Markdown documentation file.

    The function accepts only the skill-specific parameters (e.g. ``code_path``
    for Bandit, ``docker_image`` for Trivy image scan) so the LLM knows
    exactly what it needs to supply.

    Parameters
    ----------
    skill : AssessmentSkill
        The skill to wrap.
    intent_id : str
        Injected into the reconstructed intent dict passed to the skill.
    logger : JobLogger or None
        Injected logger; ``None`` when running via ``adk web``.
    """
    # Each skill type has a different parameter name.  We build the tool
    # dynamically based on the skill's accepted_parameters list.
    param_name = skill.accepted_parameters[0] if skill.accepted_parameters else "target"

    # The docstring is the primary mechanism by which the LLM learns about
    # this tool.  We combine the skill's description with the full Markdown
    # documentation so the model has rich context.
    tool_docstring = (
        f"{skill.description}\n\n"
        f"Use this tool when the request matches the following description:\n\n"
        f"{skill.docs_content}\n\n"
        f"Args:\n"
        f"    {param_name}: The target for this assessment "
        f"(see documentation above for the expected format).\n\n"
        f"Returns:\n"
        f"    A structured security assessment report."
    )

    # Create a closure capturing skill, intent_id, logger, and param_name.
    # The closure reconstructs the minimal intent dict that the existing tool
    # wrappers (bandit_assessment.py, trivy_scan.py) expect.
    def _tool_fn(**kwargs: Any) -> Dict[str, Any]:
        target_value = kwargs.get(param_name)
        # The schema declares a string, but LLMs pass this argument in three
        # shapes: a plain string, a structured object copied from the intent
        # (e.g. {"path": "..."}), or that same object SERIALISED INTO A
        # STRING ('{"path": "..."}').  Normalise the last two to the target
        # string instead of failing the assessment.
        if isinstance(target_value, str) and target_value.lstrip().startswith("{"):
            try:
                parsed = json.loads(target_value)
                if isinstance(parsed, dict):
                    target_value = parsed
            except ValueError:
                pass  # not JSON after all — keep the string as-is
        if isinstance(target_value, dict):
            target_value = (
                target_value.get("path")
                or target_value.get("name")
                or next(iter(target_value.values()), None)
            )
        # Reconstruct a minimal intent dict from the parameter the LLM provided.
        mini_intent = {
            "intentId": intent_id,
            "parameters": {param_name: target_value},
        }
        # The bandit skill uses a nested parameter: codeReference.path
        # Translate to the format the tool wrapper expects.
        if param_name == "codeReference":
            mini_intent["parameters"] = {
                "codeReference": {"path": target_value}
            }
        # Use NullLogger when no real job logger is available (adk web context).
        effective_logger = logger if logger is not None else NullLogger()
        return skill.execute(mini_intent, effective_logger)

    # Give the function a name and docstring that ADK will use for the tool.
    # Python's function name becomes the tool's name in the LLM's tool calls.
    _tool_fn.__name__ = skill.name.replace("-", "_")
    _tool_fn.__doc__ = tool_docstring

    # ADK uses inspect.signature() — not __annotations__ — to build the JSON
    # schema it sends to the LLM.  With a **kwargs signature, ADK sees no named
    # parameters and the LLM never receives the right argument name.
    # Setting __signature__ overrides what inspect.signature() returns so ADK
    # generates a schema with exactly one named string parameter for this skill.
    _tool_fn.__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter(
                param_name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=str,
            )
        ],
        return_annotation=dict,
    )

    return FunctionTool(_tool_fn)


def load_skills(skills_dir: Optional[Path] = None) -> SkillRegistry:
    """
    Discover, import, and register all assessment skills.

    This function scans the ``skills/`` directory for files matching the
    pattern ``*_skill.py``.  Each such file must expose a module-level
    constant named ``SKILL`` of type ``AssessmentSkill``.

    For every discovered skill, the function also loads the corresponding
    Markdown description file at ``docs/skills/<skill-name>.md``.  If that
    file is missing, startup is aborted with a clear error message, because
    the LLM agent relies on those files to understand what each skill does.

    Parameters
    ----------
    skills_dir : Path, optional
        Override the default ``skills/`` directory.  Used in tests.

    Returns
    -------
    SkillRegistry
        A registry populated with all discovered skills.
    """
    base_dir = skills_dir or Path(__file__).resolve().parent.parent / "skills"
    skills: List[AssessmentSkill] = []

    for path in sorted(base_dir.glob("*_skill.py")):
        # Dynamically import the skill module (e.g. skills.bandit_skill).
        module_name = f"skills.{path.stem}"
        module = importlib.import_module(module_name)

        # Every skill module must expose a SKILL constant.
        skill_obj = getattr(module, "SKILL", None)
        if not isinstance(skill_obj, AssessmentSkill):
            raise TypeError(
                f"{module_name}.SKILL must be an instance of AssessmentSkill, "
                f"got {type(skill_obj)!r}"
            )
        if not inspect.isfunction(skill_obj.execute):
            raise TypeError(
                f"{module_name}.SKILL.execute must be a plain function"
            )

        # Load the Markdown documentation file for this skill.
        # This file is mandatory — without it the LLM cannot make informed
        # routing decisions.
        docs_path = _DOCS_DIR / f"{skill_obj.name}.md"
        if not docs_path.exists():
            raise FileNotFoundError(
                f"Missing documentation file for skill '{skill_obj.name}': "
                f"{docs_path}\n"
                "Every skill must have a corresponding Markdown description "
                "in docs/skills/.  "
                "Please create the file and restart the service."
            )
        docs_content = docs_path.read_text(encoding="utf-8")

        # Re-create the skill with the docs content attached.
        # (AssessmentSkill is a frozen dataclass, so we cannot mutate it.)
        skill_with_docs = AssessmentSkill(
            name=skill_obj.name,
            description=skill_obj.description,
            assessment_types=skill_obj.assessment_types,
            accepted_parameters=skill_obj.accepted_parameters,
            execute=skill_obj.execute,
            docs_content=docs_content,
        )
        skills.append(skill_with_docs)

    return SkillRegistry(skills)
