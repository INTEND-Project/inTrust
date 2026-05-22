from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from tools.trivy_scan import scan_k8_cluster


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    target = intent.get("parameters", {}).get("clusterName")
    logger.info(
        "skill.trivy_k8s",
        "[Skill Execution]\n"
        "Starting Trivy Kubernetes cluster scan...\n"
        f"target={target}",
    )
    result = scan_k8_cluster(intent, logger)
    if result.get("status") == "FAILED":
        logger.error("skill.trivy_k8s", result.get("error", "Trivy Kubernetes scan failed"))
    else:
        logger.info("skill.trivy_k8s", result.get("explanation", "Trivy Kubernetes scan completed"))
    return result


SKILL = AssessmentSkill(
    name="trivy-kubernetes",
    description="Runs Trivy Kubernetes scanning against a cluster or context.",
    assessment_types=[
        "kubernetes_security",
        "k8s_security",
        "cluster_scan",
        "trivy_k8s",
        "kubernetes",
    ],
    accepted_parameters=["clusterName"],
    execute=execute,
)
