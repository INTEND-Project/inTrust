from typing import Any, Dict

from google.adk.agents import LlmAgent

from .skill_loader import AssessmentSkill, SkillRegistry


AGENT_NAME = "InTrustRuntimeOrchestrator"

runtime_agent = LlmAgent(
    name=AGENT_NAME,
    model="gemini-2.0-flash-lite",
    instruction=(
        "You are the InTrust Runtime Orchestrator. Interpret TM Forum Intent "
        "requests, identify the requested trustworthiness assessment, select "
        "the most suitable dynamically loaded skill, and return structured "
        "TM Forum compatible reports."
    ),
    description=(
        "Selects and executes trustworthiness assessment skills for submitted "
        "TM Forum intents."
    ),
)


class RuntimeOrchestrator:
    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self.agent_name = runtime_agent.name

    def select_skill(self, intent: Dict[str, Any]) -> AssessmentSkill:
        return self.registry.select(intent)

    def execute(self, intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
        skill = self.select_skill(intent)
        logger.info("orchestrator", f"Selected skill: {skill.name}")
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
