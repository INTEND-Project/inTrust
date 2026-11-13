---
# Copyright (c) 2025-2026 SINTEF Digital
# Copyright (c) 2026 Ericsson AB
#   Ericsson AB: interpretation caveats (severity filter, absent finding
#     kinds, vulnerability DB scope).
# SPDX-License-Identifier: MIT
name: trivy-docker-image
description: Scans Docker images for high and critical vulnerabilities using Trivy.
---

# Trivy Docker Image Security Assessment

Use this skill when the intent asks to scan a container image, Docker image, or
containerized application for known vulnerabilities.

## Inputs

Expected TM Forum intent shape:

```json
{
  "intentId": "intent-001",
  "parameters": {
    "dockerImage": "python:3.11-slim"
  }
}
```

The required parameter is `parameters.dockerImage`.

## Execution

Run the `scan_docker_image` implementation. It invokes the packaged Trivy
binary, scans the image, parses JSON output, and summarizes findings.

## Output

The skill returns the raw Trivy result together with a normalised `facts`
object:

```json
{
  "status": "SUCCESS",
  "assessment_type": "docker_image_security",
  "tool": "Trivy",
  "facts": { "shape": "findingList", "worstSeverity": "CRITICAL", "...": "..." },
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
  specific to this codebase's own logic, will not appear.
- **Package vulnerabilities require `fixedVersion` for action.** The
  normalizer reports the installed version and the fixed version where Trivy
  supplies one. The fixed version is the action: update the package to that
  version or later. Where no fix is available, Trivy records the defect but
  remediation requires determining reachability and mitigating at the
  boundary, not updating a dependency.

Report the package name, installed version, and `fixedVersion` from each
vulnerability finding, carry every `scopeLimitations` entry, and treat the
absence of a fixed version as requiring separate mitigation steps rather than
as making the finding less urgent.
