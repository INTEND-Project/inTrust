---
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

The skill invokes the packaged Trivy binary against the requested
Kubernetes cluster and summarizes the report.

## Output

Return a TM Forum aligned report with the intent ID, lifecycle status,
assessment type, target cluster, tool metadata, metrics, assessment verdict, and
explanation.
