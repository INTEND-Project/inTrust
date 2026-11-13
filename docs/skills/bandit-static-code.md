---
# Copyright (c) 2025-2026 SINTEF Digital
# Copyright (c) 2026 Ericsson AB
#   Ericsson AB: interpretation caveats (cleartext credentials in output,
#     findings are pattern matches).
# SPDX-License-Identifier: MIT
name: bandit-static-code
description: Evaluates Python source code for security vulnerabilities using Bandit.
---

# Bandit Static Code Security Assessment

Use this skill when the intent asks for Python source code security assessment,
static application security testing, insecure coding pattern detection, or
Bandit-based vulnerability scanning.

## Inputs

Expected TM Forum intent shape:

```json
{
  "intentId": "intent-456",
  "parameters": {
    "codeReference": {
      "path": "/path/to/python/codebase"
    }
  }
}
```

The required parameter is `parameters.codeReference.path`.

## Execution

Run the `run_bandit_assessment` implementation. It invokes Bandit recursively,
parses JSON output, and returns a structured assessment report that is
normalised before leaving the skill.

## Output

The skill returns the raw Bandit result together with a normalised `facts`
object:

```json
{
  "status": "SUCCESS",
  "assessment_type": "static_code_analysis",
  "tool": "Bandit",
  "facts": { "shape": "findingList", "worstSeverity": "HIGH", "...": "..." },
  "raw": { "results": [...], "metrics": {...}, "..." }
}
```

`tools/bandit_normalizer.py` parses Bandit's `results` array into `Finding`
objects with three separate detail tiers (`businessImpact`, `technicalDetail`,
`evidence`, plus `remediation`), derives severity counts from the findings
actually built rather than copying Bandit's `issue_summary` (both are kept in
`facts.method`, so a discrepancy between them is visible), and records coverage
metrics (`linesOfCode`, `filesAnalysed`, `suppressedByNosec`) from Bandit's
`metrics._totals`. Severity is Bandit's and is not recomputed: the ontology's
`spa:Threshold` individuals classify swept metric values, which is a different
operation from relabelling a verdict the tool already reached, so unlike the
MIA skill there is no threshold classification here.

**Do not parse the findings yourself, and do not recompute any figure in
`facts`.** Every number and severity in the report must come from `facts`
verbatim. The `raw` output is retained as evidence so a reader can re-derive
figures independently, but reading it to build the report introduces two
unsafe properties:

- **Bandit prints credential values in cleartext**, in both the `code` snippet
  and the `issue_text` prose, and the snippet includes context lines Bandit
  did not flag (in the observed run, line 14's flagged secret arrived beside
  line 13's unflagged client id). The normalizer masks every quoted literal
  before it reaches `facts`; `evidence.redacted` and `evidence.redactionNote`
  say so. The value must not be reintroduced from `raw` into any report — that
  is the reason `raw` must not be read for reporting, not merely a style
  preference.
- **A finding is a pattern match, not a proof.** Bandit reports a confidence
  per finding (`technicalDetail.confidence`) and a LOW-confidence finding is
  correspondingly more likely to be a false positive; an empty result means no
  checked pattern matched, not that no vulnerability exists. Both facts are
  already stated in `facts.scopeLimitations`, which must be carried into the
  report.

Carry every `scopeLimitations` entry into the report, report the file and line
so a finding stays checkable, and do not present a LOW-severity finding as
clean.
