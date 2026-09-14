"""
Synthetic distractor skills for the registry-size experiment.

The submitted benchmark exposes four capabilities (three supported scenarios
plus the Kubernetes routing distractor), which does not stress the shared
context of the single-agent architecture.  This module grows the registry
with additional plausible security/compliance capabilities so both
architectures can be compared at 4, 8, 16 and 32 skills.

Each distractor is a full ``AssessmentSkill`` (name, description, Markdown-
style documentation of the same length and shape as the real skills), so it
costs the same context as a real skill: in Architecture B it is one more tool,
in Architecture A one more specialist agent.  Its ``execute`` always reports
FAILED — like the Kubernetes distractor, selecting it is always a mis-route.

Catalogue constraints (keep them when editing):
- no functional overlap with the three supported scenarios (Python static
  code analysis, filesystem dependency/secret/misconfiguration scanning,
  container-image vulnerability scanning), so ground truth stays unambiguous;
- no overlap with the gatekeeping request domains (see the unsupported
  intents), so an unsupported request never becomes supported by accident;
- the order is fixed and prefix-stable: the 8-skill registry is a subset of
  the 16-skill one, which is a subset of the 32-skill one.

Opt-in only: experiments default to ``extra_distractor_skills = 0``.
"""

from typing import Any, Dict, List

from orchestrator.skill_loader import AssessmentSkill

from . import routing_analysis

# (name, one-line description, what the skill is for, what the target is)
_CATALOGUE = [
    ("sbom-generator",
     "Generates a software bill of materials for a release artifact.",
     "produce an inventory (SBOM, SPDX or CycloneDX) of the components contained in a release artifact, without assessing vulnerabilities.",
     "the release artifact identifier"),
    ("cloud-account-posture",
     "Audits a public-cloud account's configuration against CIS benchmarks.",
     "evaluate an AWS, Azure or GCP account's configuration against CIS cloud benchmarks through the provider APIs.",
     "the cloud account or subscription ID"),
    ("dockerfile-linter",
     "Lints Dockerfile build recipes for build best practices.",
     "check the text of a Dockerfile for build best practices such as a non-root user, pinned base tags and minimal layers, without scanning any built image.",
     "the path of the Dockerfile"),
    ("ci-workflow-auditor",
     "Reviews CI/CD pipeline definitions for unsafe permissions.",
     "review CI/CD workflow definitions (GitHub Actions, GitLab CI) for over-broad tokens, untrusted third-party actions and unsafe triggers.",
     "the repository slug whose workflows to review"),
    ("terraform-policy-checker",
     "Evaluates Terraform plans against organisational policies.",
     "evaluate a Terraform plan against organisational OPA/Rego policies before it is applied.",
     "the path of the Terraform plan JSON file"),
    ("helm-chart-linter",
     "Validates Helm chart templates and values.",
     "validate Helm chart templates and values files for schema errors, deprecated API versions and missing resource limits.",
     "the chart name or path"),
    ("openapi-spec-linter",
     "Lints OpenAPI specifications for insecure API design.",
     "lint an OpenAPI specification document for missing authentication schemes, unbounded inputs and insecure design choices, without sending traffic to any running service.",
     "the path or URL of the specification document"),
    ("javascript-security-linter",
     "Security-focused linting of JavaScript and TypeScript sources.",
     "apply security lint rules to JavaScript or TypeScript source code (for example eval usage or prototype pollution); it does not support other languages.",
     "the path of the JavaScript/TypeScript project"),
    ("database-config-auditor",
     "Checks relational database server settings for weak configuration.",
     "inspect the settings of a running PostgreSQL or MySQL server for weak authentication methods, excessive privileges and disabled audit logging.",
     "the database server connection name"),
    ("iam-policy-analyzer",
     "Analyses identity and access management policies for excess privilege.",
     "analyse IAM policy documents for over-privileged permissions and privilege-escalation paths.",
     "the IAM role or policy ARN"),
    ("auth-log-anomaly-detector",
     "Detects anomalous authentication events in log streams.",
     "detect anomalous authentication activity (impossible travel, brute-force bursts) in centralised log streams.",
     "the log stream or index name"),
    ("backup-integrity-verifier",
     "Verifies the integrity and restorability of backups.",
     "verify checksums of backup archives and perform a trial restore to confirm recovery readiness.",
     "the backup set identifier"),
    ("git-commit-signature-checker",
     "Verifies cryptographic signatures on Git commits and tags.",
     "verify that commits and release tags in a Git repository are cryptographically signed by trusted keys.",
     "the repository URL"),
    ("model-card-reviewer",
     "Reviews machine-learning model documentation for completeness.",
     "review a machine-learning model card or datasheet for missing sections required by AI-governance guidelines.",
     "the model registry identifier"),
    ("object-storage-acl-auditor",
     "Audits object-storage bucket permissions for public exposure.",
     "audit S3-compatible bucket policies and ACLs for public read or write exposure.",
     "the bucket name"),
    ("vm-baseline-hardening",
     "Checks virtual-machine templates against hardening baselines.",
     "check a virtual-machine template (AMI or qcow2) against CIS operating-system hardening baselines; it does not handle container images.",
     "the VM template identifier"),
    ("artifact-signature-verifier",
     "Verifies signatures and provenance attestations of release artifacts.",
     "verify Sigstore/cosign signatures and SLSA provenance attestations attached to a release artifact.",
     "the artifact reference"),
    ("crypto-algorithm-inventory",
     "Inventories cryptographic algorithms used by compiled binaries.",
     "inventory the cryptographic algorithms and key sizes used by compiled binaries to plan a post-quantum migration.",
     "the binary or package name"),
    ("service-mesh-policy-auditor",
     "Audits service-mesh authorization policies.",
     "audit Istio or Linkerd authorization policies for overly permissive service-to-service rules.",
     "the mesh namespace"),
    ("endpoint-agent-coverage",
     "Reports endpoint-protection agent coverage across managed devices.",
     "report which managed laptops and servers lack an up-to-date endpoint detection and response (EDR) agent.",
     "the device group name"),
    ("mfa-enrolment-reporter",
     "Reports multi-factor authentication enrolment gaps.",
     "report user accounts in the identity provider that are not enrolled in multi-factor authentication.",
     "the identity-provider tenant"),
    ("infrastructure-drift-detector",
     "Detects drift between declared and deployed infrastructure.",
     "detect differences between infrastructure-as-code declarations and the resources actually deployed in the cloud.",
     "the stack or workspace name"),
    ("cloud-audit-log-coverage",
     "Checks that cloud audit logging is enabled everywhere.",
     "check that cloud audit logging is enabled and retained across all regions and services of an account.",
     "the cloud account ID"),
    ("firmware-component-analyzer",
     "Analyses embedded-device firmware for known-vulnerable components.",
     "unpack an embedded-device firmware file and identify bundled components with known vulnerabilities; it does not accept source folders or container images.",
     "the firmware file name"),
    ("host-patch-level-reporter",
     "Reports missing operating-system patches on managed hosts.",
     "report missing operating-system security patches on managed Linux hosts from the configuration-management inventory.",
     "the host group name"),
    ("saas-sharing-auditor",
     "Finds externally shared documents in SaaS collaboration suites.",
     "find documents and folders shared publicly or with external domains in SaaS collaboration suites.",
     "the SaaS tenant name"),
    ("message-broker-acl-auditor",
     "Audits message-broker access-control lists.",
     "audit Kafka or RabbitMQ access-control lists for anonymous or wildcard access.",
     "the broker name"),
    ("serverless-permission-reviewer",
     "Reviews serverless function permissions and triggers.",
     "review serverless functions (AWS Lambda, Cloud Functions) for over-privileged execution roles and publicly invocable triggers.",
     "the function name"),
]

# Same section structure as the real skill documents in docs/skills/.
_DOC_TEMPLATE = """---
description: {description}
---

# {title}

Use this skill when the request asks to {purpose}

## Inputs

The required parameter is `parameters.target`: {target}.

## Execution

The skill invokes the corresponding assessment tooling against the target
and summarizes the findings.

## Output

Return a structured report with the intent ID, lifecycle status, assessment
type, target, tool metadata, findings, an overall verdict, and an
explanation.
"""

#: Largest supported number of distractors (32-skill registry).
MAX_DISTRACTORS = len(_CATALOGUE)


def _distractor_execute(intent: Dict[str, Any], logger: Any) -> Dict[str, Any]:
    """Every distractor call is a mis-route: report it as a failed assessment."""
    return {
        "status": "FAILED",
        "error": "distractor capability: not available in the benchmark",
    }


def make_distractor_skills(n: int) -> List[AssessmentSkill]:
    """
    Return the first ``n`` synthetic distractor skills (0 <= n <= 28).

    Each one is also registered with the routing decomposition so the results
    can report which distractor a model chose.
    """
    if not 0 <= n <= MAX_DISTRACTORS:
        raise ValueError(
            f"extra_distractor_skills must be between 0 and {MAX_DISTRACTORS}, got {n}"
        )
    skills: List[AssessmentSkill] = []
    for name, description, purpose, target in _CATALOGUE[:n]:
        docs = _DOC_TEMPLATE.format(
            description=description,
            title=name.replace("-", " ").title(),
            purpose=purpose,
            target=target,
        )
        skills.append(
            AssessmentSkill(
                name=name,
                description=description,
                assessment_types=[name.replace("-", "_")],
                accepted_parameters=["target"],
                execute=_distractor_execute,
                docs_content=docs,
            )
        )
        routing_analysis.register_skill_signature(name)
    return skills
