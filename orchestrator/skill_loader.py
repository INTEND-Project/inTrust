"""
Skill framework for InTrust.

This module defines the core building blocks of the skill system:

- ``AssessmentSkill``: a dataclass describing one assessment capability
  (e.g. Bandit static analysis, Trivy image scan).
- ``SkillRegistry``: a container that holds all loaded skills and uses an
  LLM to decide which skill best matches an incoming request.
- ``load_skills()``: a factory function that discovers and imports every
  ``*_skill.py`` file in the ``skills/`` directory and registers them.

Adding a new skill to the system requires only two things:
1. Create ``skills/<name>_skill.py`` that exposes a ``SKILL`` constant of
   type ``AssessmentSkill``.
2. Create ``docs/skills/<name>.md`` that describes the skill in plain
   English (this file is what the LLM reads to understand the skill).
No changes to the orchestrator or any other file are needed.
"""

import importlib
import inspect
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from google import genai


# Type alias for the skill execution function signature.
# Every skill's execute() function receives the raw intent dictionary and a
# JobLogger instance, and returns a result dictionary.
SkillExecuteFn = Callable[[Dict[str, Any], Any], Dict[str, Any]]

# Path to the directory that contains per-skill Markdown description files.
# These files are read at startup and fed to the LLM during skill selection.
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
        Keywords that characterise this skill's domain (used only for display
        and documentation — skill *selection* is done by the LLM).
    accepted_parameters : list of str
        Top-level keys inside the intent's ``parameters`` object that this
        skill expects (e.g. ``["codeReference"]``).
    execute : callable
        The function that performs the actual assessment.  Signature:
        ``execute(intent: dict, logger: JobLogger) -> dict``.
    docs_content : str
        Full text of the ``docs/skills/<name>.md`` file.  Loaded at startup
        by ``load_skills()`` and embedded in the LLM prompt so the model can
        reason about when to use this skill.  Skill files themselves do not
        need to set this — ``load_skills()`` fills it in automatically from
        the corresponding ``docs/skills/<name>.md`` file.
    """

    name: str
    description: str
    assessment_types: List[str]
    accepted_parameters: List[str]
    execute: SkillExecuteFn
    # Defaults to empty string so that skill files can define SKILL without
    # specifying docs_content directly.  load_skills() always overwrites this
    # with the real file content before registering the skill.
    docs_content: str = ""


class SkillRegistry:
    """
    Holds all registered skills and selects the best one for an incoming
    request using an LLM.

    The registry is populated once at startup by ``load_skills()`` and then
    passed to the ``RuntimeOrchestrator``.
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

    def select(self, request: Any) -> AssessmentSkill:
        """
        Use the LLM to choose the most appropriate skill for ``request``.

        ``request`` can be either:
        - A TM Forum Intent dictionary (the normal case), or
        - A plain string expressing the user's intent in natural language.

        The LLM is given a description of every registered skill and asked to
        return the name of the single best-matching skill, or ``"none"`` if
        the request does not match any skill.

        Raises
        ------
        ValueError
            If the LLM returns ``"none"`` (no skill is appropriate) or if the
            returned name does not match any registered skill.
        RuntimeError
            If the LLM API call fails entirely.
        """
        prompt = self._build_selection_prompt(request)

        # Configure and call the Gemini API.
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. "
                "Please add it to your .env file before starting the service."
            )
        client = genai.Client(api_key=api_key)

        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            raw_answer = response.text.strip()
        except Exception as exc:
            raise RuntimeError(
                f"LLM skill selection failed: {exc}"
            ) from exc

        # The model is instructed to respond with just a skill name or "none".
        # We strip extra punctuation/whitespace that the model might add.
        chosen_name = raw_answer.strip().strip('"').strip("'").lower()

        if chosen_name == "none":
            raise ValueError(
                "No suitable assessment skill found for the given request. "
                "InTrust currently supports Python static code analysis "
                "(Bandit) and filesystem, Docker image, and Kubernetes "
                "cluster scanning (Trivy). "
                "Please revise your request to match one of these capabilities."
            )

        # Try to find the chosen skill by name (case-insensitive).
        matched_skill = next(
            (s for s in self.list() if s.name.lower() == chosen_name),
            None,
        )
        if matched_skill is None:
            raise ValueError(
                f"The LLM selected skill '{chosen_name}', but no skill with "
                f"that name is registered. "
                f"Available skills: {[s.name for s in self.list()]}"
            )

        return matched_skill

    def _build_selection_prompt(self, request: Any) -> str:
        """
        Build the prompt that is sent to the LLM for skill selection.

        The prompt contains:
        - A description of the task (choose a skill).
        - A serialised representation of the incoming request.
        - A detailed description of every available skill, including its
          full Markdown documentation so the LLM has rich context.
        - Strict output instructions (respond with exactly one skill name
          or the word "none").
        """
        # Serialise the request so the LLM can read it regardless of type.
        if isinstance(request, dict):
            request_text = json.dumps(request, indent=2)
        else:
            request_text = str(request)

        # Build a section for each skill with all available metadata.
        skill_sections = []
        for skill in self.list():
            section = (
                f"### Skill: {skill.name}\n"
                f"Short description: {skill.description}\n"
                f"Accepted intent parameters: {', '.join(skill.accepted_parameters)}\n"
                f"Associated assessment keywords: {', '.join(skill.assessment_types)}\n"
                f"\nFull skill documentation:\n{skill.docs_content}"
            )
            skill_sections.append(section)

        skills_text = "\n\n---\n\n".join(skill_sections)

        return (
            "You are a security assessment routing system. "
            "Your only job is to read an incoming assessment request and "
            "decide which of the available skills should handle it.\n\n"
            "# Incoming Request\n\n"
            f"{request_text}\n\n"
            "# Available Skills\n\n"
            f"{skills_text}\n\n"
            "# Instructions\n\n"
            "Think step by step:\n"
            "1. What kind of assessment is being requested?\n"
            "2. Which skill's documentation best matches that request?\n"
            "3. If no skill is suitable, respond with the word: none\n\n"
            "Respond with ONLY the skill name (exactly as shown above) "
            "or the word 'none'. "
            "Do not include any explanation, punctuation, or extra text in "
            "your final answer — just the skill name or 'none'."
        )


def load_skills(skills_dir: Optional[Path] = None) -> SkillRegistry:
    """
    Discover, import, and register all assessment skills.

    This function scans the ``skills/`` directory for files matching the
    pattern ``*_skill.py``.  Each such file must expose a module-level
    constant named ``SKILL`` of type ``AssessmentSkill``.

    For every discovered skill, the function also looks for a corresponding
    Markdown description file at ``docs/skills/<skill-name>.md``.  If that
    file is missing, startup is aborted with a clear error message, because
    the LLM relies on those files to understand what each skill does.

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
