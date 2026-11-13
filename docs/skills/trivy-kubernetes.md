---
# Copyright (c) 2025-2026 SINTEF Digital
# Copyright (c) 2026 Ericsson AB
#   Ericsson AB: interpretation caveats (severity filter, absent finding
#     kinds, vulnerability DB scope).
# SPDX-License-Identifier: MIT
name: trivy-kubernetes
description: Evaluates Kubernetes cluster security and compliance posture using Trivy.
---

# Trivy Kubernetes Cluster Security Assessment

Use this skill when the intent asks to evaluate a Kubernetes cluster, K8s
configuration, workload security posture, or cluster compliance using Trivy.

## Inputs

Expected TM Forum intent shape:

```json
{
  "intentId": "intent-003",
  "parameters": {
    "clusterName": "my-cluster"
  }
}
```

The required parameter is `parameters.clusterName`.

## Execution

Run the `scan_k8_cluster` implementation. It invokes the packaged Trivy binary
against the requested Kubernetes cluster and summarizes the report.

## Output

The skill returns the raw Trivy result together with a normalised `facts`
object:

```json
{
  "status": "SUCCESS",
  "assessment_type": "kubernetes_security",
  "tool": "Trivy",
  "facts": { "shape": "findingList", "worstSeverity": "HIGH", "...": "..." },
  "raw": { "Results": [...] }
}
```

One normalizer serves all three Trivy skills because they differ in what Trivy
is pointed at, not in what Trivy returns. The skill name is derived from
`assessment_type`. `tools/trivy_normalizer.py` flattens Trivy's per-target
`Results` into findings across its four structurally distinct finding arrays —
`Vulnerabilities`, `Secrets`, `Misconfigurations`, `Licenses` — each with its
own field names for the same concepts, which is why there is a converter per
kind. Each finding gets three separate detail tiers (`businessImpact`,
`technicalDetail`, `evidence`, plus `remediation`). Counts are derived from
the findings actually built and recorded in `facts.method` (`severityCounts`,
`findingKindCounts`). Severity is Trivy's and is carried through rather than
recomputed; the ontology's `spa:Threshold` individuals classify swept metric
values, a different operation from relabelling a verdict a tool already
reached.

**Do not parse `raw` yourself, and do not recompute any figure in `facts`.**
Every number and severity in the report must come from `facts` verbatim. The
raw result is retained as evidence so a reader can re-derive figures
independently. Four properties of this tool's output make hand-reading it
unsafe:

- **The severity filter bounds every conclusion.** Trivy is invoked at
  `HIGH,CRITICAL` only, so LOW and MEDIUM findings are never collected. An
  empty result establishes "nothing found at HIGH or CRITICAL", NOT "clean" —
  and the empty result is exactly the one most likely to be over-read, since
  no findings are present to suggest the scan was partial. This is the first
  entry in `facts.scopeLimitations` on every result and must be carried into
  the report.
- **An absent finding kind is not a clean result for that kind.** A scanner
  that did not run produces no findings, indistinguishably from one that found
  nothing. `facts.scopeLimitations` states which scanner classes produced
  results.
- **Trivy's database bounds the result.** It reports issues already published
  in its vulnerability and policy databases; an unpublished defect, or one
  specific to this deployment's own logic, will not appear.
- **Misconfiguration findings dominate cluster scans.** The kubernetes skill
  primarily reports deployment-time hardening issues — privilege escalation,
  capability grants, service exposure, resource limits — checked against the
  cluster's declared configuration. Trivy's `Results` targets are cluster
  resources (namespaces, deployments, pods) rather than files. Report the
  resource name, namespace, and the check ID from each finding's
  `technicalDetail` so a finding is checkable against the running cluster, not
  reduced to a count.

Report the target resource and the check that failed so a finding stays
checkable, carry every `scopeLimitations` entry, and treat a misconfiguration
finding as a statement about the configuration as written rather than about
how the cluster is actually deployed.
