import importlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List


BASE_DIR = Path(__file__).resolve().parent
SKILLS_DIR = BASE_DIR / "skills"


def _skill_dir(skill_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "-", skill_id.strip().lower())
    safe_id = safe_id.replace("_", "-")
    safe_id = re.sub(r"-+", "-", safe_id).strip("-")
    return SKILLS_DIR / safe_id


def _load_skill_metadata(skill_path: Path) -> Dict[str, Any]:
    with (skill_path / "metadata.json").open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_skill_instruction(skill_path: Path) -> str:
    skill_file = skill_path / "SKILL.md"
    if not skill_file.exists():
        return ""
    return skill_file.read_text(encoding="utf-8")


def _iter_skill_paths() -> List[Path]:
    if not SKILLS_DIR.exists():
        return []
    return sorted(
        path
        for path in SKILLS_DIR.iterdir()
        if path.is_dir() and (path / "metadata.json").exists()
    )


def list_assessment_skills() -> Dict[str, Any]:
    """List the assessment skills currently available to the InTrust agent."""
    skills = []
    for skill_path in _iter_skill_paths():
        metadata = _load_skill_metadata(skill_path)
        skills.append(
            {
                "id": metadata.get("id", skill_path.name),
                "name": metadata.get("name"),
                "description": metadata.get("description"),
                "assessment_types": metadata.get("assessment_types", []),
                "required_parameters": metadata.get("required_parameters", []),
                "executable": bool(
                    metadata.get("tool_module") and metadata.get("tool_function")
                ),
            }
        )
    return {"status": "SUCCESS", "skills": skills}


def inspect_assessment_skill(skill_id: str) -> Dict[str, Any]:
    """Return metadata and SKILL.md instructions for a specific assessment skill."""
    skill_path = _skill_dir(skill_id)
    if not (skill_path / "metadata.json").exists():
        return {
            "status": "FAILED",
            "error": f"Skill not found: {skill_id}",
            "available_skills": list_assessment_skills().get("skills", []),
        }

    return {
        "status": "SUCCESS",
        "metadata": _load_skill_metadata(skill_path),
        "instructions": _load_skill_instruction(skill_path),
    }


def execute_assessment_skill(
    skill_id: str, intent_request: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute an assessment skill against a TM Forum intent request."""
    skill_path = _skill_dir(skill_id)
    if not (skill_path / "metadata.json").exists():
        return {
            "status": "FAILED",
            "error": f"Skill not found: {skill_id}",
            "available_skills": list_assessment_skills().get("skills", []),
        }

    metadata = _load_skill_metadata(skill_path)
    tool_module = metadata.get("tool_module")
    tool_function = metadata.get("tool_function")
    if not tool_module or not tool_function:
        return {
            "intentId": intent_request.get("intentId", "unknown"),
            "status": "PENDING_IMPLEMENTATION",
            "skill_id": metadata.get("id", skill_id),
            "assessment_type": metadata.get("assessment_types", [None])[0],
            "required_parameters": metadata.get("required_parameters", []),
            "explanation": (
                "This skill is registered, but no executable tool implementation "
                "has been configured yet."
            ),
        }

    package = __package__ or Path(__file__).resolve().parent.name
    module = importlib.import_module(f".{tool_module}", package=package)
    assessment_func = getattr(module, tool_function)
    result = assessment_func(intent_request)
    if isinstance(result, dict):
        result.setdefault("skill_id", metadata.get("id", skill_id))
        result.setdefault("skill_name", metadata.get("name"))
    return result


def create_assessment_skill(
    skill_id: str,
    name: str,
    description: str,
    assessment_types: List[str],
    required_parameters: List[str],
) -> Dict[str, Any]:
    """Create a file-backed skill skeleton when no existing skill matches an intent."""
    skill_path = _skill_dir(skill_id)
    if skill_path.exists():
        return {
            "status": "FAILED",
            "error": f"Skill already exists: {skill_path.name}",
            "skill": inspect_assessment_skill(skill_path.name),
        }

    skill_path.mkdir(parents=True, exist_ok=False)
    metadata = {
        "id": skill_path.name,
        "name": name,
        "description": description,
        "assessment_types": assessment_types,
        "required_parameters": required_parameters,
        "tool_module": None,
        "tool_function": None,
        "output_key": f"{skill_path.name}_assessment",
    }

    (skill_path / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    (skill_path / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {skill_path.name}",
                f"description: {description}",
                "---",
                "",
                f"# {name}",
                "",
                description,
                "",
                "## Inputs",
                "",
                "Required parameters:",
                *[f"- `{parameter}`" for parameter in required_parameters],
                "",
                "## Execution",
                "",
                "No executable tool is registered yet. Implement the assessment ",
                "function in `tools/` and update `metadata.json` with its module ",
                "and function name.",
                "",
                "## Output",
                "",
                "Return a TM Forum aligned assessment report.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return {"status": "SUCCESS", "skill": metadata}
