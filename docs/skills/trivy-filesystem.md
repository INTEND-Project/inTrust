---
# Copyright (c) 2025-2026 SINTEF Digital
# Copyright (c) 2026 Ericsson AB
#   Ericsson AB: interpretation caveats (severity filter, absent finding
#     kinds, vulnerability DB scope).
# SPDX-License-Identifier: MIT
name: trivy-filesystem
description: Scans a local directory for vulnerabilities, secrets, and misconfigurations using Trivy.
---

# Trivy File System Security Assessment

Use this skill when the intent asks to scan a local directory, repository,
filesystem path, software bill of materials source, secrets, or configuration
files for vulnerabilities and misconfigurations.

## Inputs

Expected TM Forum intent shape:

```json
{
  "intentId": "intent-002",
  "parameters": {
    "fsPath": "/opt/project"
  }
}
```

The required parameter is `parameters.fsPath`.

## Execution

Run the `scan_fs` implementation. It invokes the packaged Trivy binary with
filesystem scanners enabled and returns summarized findings.

## Output

The skill returns the raw Trivy result together with a normalised `facts`
object:

```json
{
  "status": "SUCCESS",
  "assessment_type": "filesystem_security",
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
independently. Five properties of this tool's output make hand-reading it
unsafe:

- **The severity filter bounds every conclusion.** Trivy is invoked at
  `HIGH,CRITICAL` only, so LOW and MEDIUM findings are never collected. An
  empty result establishes "nothing found at HIGH or CRITICAL", NOT "clean" —
  and the empty result is exactly the one most likely to be over-read, since
  no findings are present to suggest the scan was partial. This is the first
  entry in `facts.scopeLimitations` on every result and must be carried into
  the report.
- **Trivy masks only the value it matched.** The context lines it returns
  either side of a secret match are verbatim source; in the observed
  filesystem scan the masked `CLIENT_SECRET` line arrived beside unmasked
  `TENANT_ID` and `CLIENT_ID` assignments. The normalizer masks every quoted
  literal before it reaches `facts`, and sets `evidence.maskedByTool` and
  `evidence.maskedDuringNormalisation` so a reader knows the snippet is not a
  verbatim copy. Do not reintroduce any credential from `raw` into any
  report — this is the reason `raw` must not be read for reporting.
- **An absent finding kind is not a clean result for that kind.** A scanner
  that did not run produces no findings, indistinguishably from one that found
  nothing. `facts.scopeLimitations` states which scanner classes produced
  results. For this filesystem skill, licence detection is not among the
  scanners enabled, so "no licence findings" is not a licence review.
- **Trivy's database bounds the result.** It reports issues already published
  in its vulnerability and policy databases; an unpublished defect, or one
  specific to this codebase's own logic, will not appear.
- **Multiple `Results` targets contribute to one report.** Trivy groups
  findings by target (lock files, config files, source files). The finding
  count is cumulative across targets; report the specific file path and line
  number from each finding's `evidence` and `technicalDetail` so the finding
  stays checkable rather than merged into an aggregate.

Report the target and line so a finding stays checkable, carry every
`scopeLimitations` entry, and report exactly what Trivy found rather than
inferring what was not enabled.
