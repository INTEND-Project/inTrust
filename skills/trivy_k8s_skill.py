"""
Trivy Kubernetes cluster scanning skill.

This skill runs Trivy against a Kubernetes cluster (or a specific kubeconfig
context) to detect security misconfigurations, vulnerabilities in running
workloads, and compliance issues across cluster resources.

Use it when the request asks for Kubernetes security assessment, cluster
hardening analysis, workload vulnerability scanning, or K8s compliance
checking.

The intent must provide the cluster name or kubeconfig context name under
``parameters.clusterName``.

See also: docs/skills/trivy-kubernetes.md
"""

from typing import Any, Dict

from orchestrator.skill_loader import AssessmentSkill
from tools.trivy_scan import scan_k8_cluster


def execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    """
    Run Trivy Kubernetes scan against the cluster specified in the intent.

    Parameters
    ----------
    intent : dict
        TM Forum Intent.  Must contain ``parameters.clusterName``.
    logger : JobLogger
        Bound logger for this job.

    Returns
    -------
    dict
        Assessment result with security findings across cluster resources,
        along with verdict, explanation, and recommendations.
    """
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
