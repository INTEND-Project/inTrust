# Copyright (c) 2025-2026 SINTEF Digital
# Copyright (c) 2026 Ericsson AB
#   Ericsson AB: normalises Trivy output into canonical facts before it leaves
#     the skill.
# SPDX-License-Identifier: MIT
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
from orchestrator.skill_result import normalised_result
from tools.trivy_normalizer import normalize
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
        ``{status, assessment_type, tool, facts, raw}`` — the canonical facts
        every audience rendition is projected from, beside the unmodified Trivy
        output they were derived from.
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
        return result

    logger.info("skill.trivy_k8s", result.get("explanation", "Trivy Kubernetes scan completed"))

    # Normalise before the result leaves the skill.  Deriving the findings here
    # rather than leaving Trivy's raw cluster report for the report-composing
    # model to read is what keeps every audience rendition traceable to the same
    # findings — and it is where the scan's severity filter (HIGH,CRITICAL only)
    # is recorded as a stated scope limitation, so a clean result is never
    # reported as an unqualified all-clear.
    facts = normalize(result, intent=intent)
    return normalised_result(
        facts,
        raw_result=result,
        assessment_type="kubernetes_security",
        tool="Trivy",
        logger=logger,
        component="skill.trivy_k8s",
    )


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
