import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


SkillExecuteFn = Callable[[Dict[str, Any], Any], Dict[str, Any]]


@dataclass(frozen=True)
class AssessmentSkill:
    name: str
    description: str
    assessment_types: List[str]
    accepted_parameters: List[str]
    execute: SkillExecuteFn

    def matches(self, intent: Dict[str, Any]) -> int:
        text_parts = [
            str(intent.get("name", "")),
            str(intent.get("type", "")),
            str(intent.get("description", "")),
            str(intent.get("assessmentType", "")),
            str(intent.get("parameters", {}).get("assessmentType", "")),
        ]
        params = intent.get("parameters", {})
        score = 0
        haystack = " ".join(text_parts).lower()
        for assessment_type in self.assessment_types:
            token = assessment_type.lower()
            if token and token in haystack:
                score += 5
        for parameter in self.accepted_parameters:
            if parameter in params:
                score += 2
        return score


class SkillRegistry:
    def __init__(self, skills: List[AssessmentSkill]):
        self._skills = {skill.name: skill for skill in skills}

    def list(self) -> List[AssessmentSkill]:
        return list(self._skills.values())

    def get(self, name: str) -> Optional[AssessmentSkill]:
        return self._skills.get(name)

    def select(self, intent: Dict[str, Any]) -> AssessmentSkill:
        ranked = sorted(
            ((skill.matches(intent), skill) for skill in self.list()),
            key=lambda item: item[0],
            reverse=True,
        )
        if not ranked or ranked[0][0] <= 0:
            raise ValueError("No matching assessment skill found for intent")
        return ranked[0][1]


def load_skills(skills_dir: Path | None = None) -> SkillRegistry:
    base_dir = skills_dir or Path(__file__).resolve().parent.parent / "skills"
    skills: List[AssessmentSkill] = []
    for path in sorted(base_dir.glob("*_skill.py")):
        module_name = f"skills.{path.stem}"
        module = importlib.import_module(module_name)
        skill = getattr(module, "SKILL", None)
        if not isinstance(skill, AssessmentSkill):
            raise TypeError(f"{module_name}.SKILL must be an AssessmentSkill")
        if not inspect.isfunction(skill.execute):
            raise TypeError(f"{module_name}.SKILL.execute must be a function")
        skills.append(skill)
    return SkillRegistry(skills)
