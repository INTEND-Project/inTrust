from typing import Any, Dict

from .skill_loader import AssessmentSkill, SkillRegistry


AGENT_NAME = "InTrustRuntimeOrchestrator"


class RuntimeOrchestrator:
    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self.agent_name = AGENT_NAME

    def select_skill(self, intent: Dict[str, Any]) -> AssessmentSkill:
        return self.registry.select(intent)

    def execute(self, intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
        skill = self.select_skill(intent)
        assessment_type = (
            intent.get("parameters", {}).get("assessmentType")
            or intent.get("assessmentType")
            or intent.get("type")
        )
        logger.info(
            "orchestrator",
            "[Orchestrator]\n"
            f"Selected skill: {skill.name}\n"
            f"Reason: assessmentType={assessment_type}",
        )
        result = skill.execute(intent, logger)
        return self._standardize_report(intent, skill, result)

    def _standardize_report(
        self,
        intent: Dict[str, Any],
        skill: AssessmentSkill,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        intent_id = intent.get("intentId") or intent.get("id") or "unknown"
        status = "completed" if result.get("status") in {"SUCCESS", "COMPLETED"} else "failed"
        return {
            "intentId": intent_id,
            "lifecycleStatus": status,
            "assessmentType": result.get("assessment_type")
            or intent.get("parameters", {}).get("assessmentType")
            or intent.get("assessmentType"),
            "skill": skill.name,
            "parameters": intent.get("parameters", {}),
            "metrics": result.get("metrics") or result.get("issue_summary") or {},
            "provenance": {
                "agent": self.agent_name,
                "skill": skill.name,
                "tool": result.get("tool"),
                "toolVersion": result.get("version"),
            },
            "result": result,
            "explanation": result.get("explanation"),
            "recommendations": result.get("recommendations"),
        }
