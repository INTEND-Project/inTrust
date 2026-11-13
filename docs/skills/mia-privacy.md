---
# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
name: mia-privacy
description: Evaluates machine learning model privacy resilience against membership inference attacks.
---

# Membership Inference Privacy Assessment

Use this skill when the intent asks whether a machine learning model leaks
training-set membership information, needs privacy auditing, or mentions
membership inference attacks.

## Inputs

Expected TM Forum intent shape:

```json
{
  "intentId": "intent-123",
  "parameters": {
    "model": {
	  "type": "classification model",
      "path": "/data/model.pt"
    },
  "shadowData": {
      "type": "synthetic"
    }
  }
}
```

The expected parameters are `parameters.model` and `parameters.shadowData`.

When calling this tool, always pass the intent's top-level `intentId` as the
`intentId` argument, together with `model` and `shadowData`. The MIA service
is queried by intent id, so the exact `intentId` from the intent must be
forwarded.

## Execution

Run the `run_mia_assessment` implementation. It delegates the membership
inference assessment to the remote MIA service (initiating the assessment
and retrieving its result, keyed by the intent id) and returns the model
privacy metrics.

## Output

The skill returns the raw MIA result together with a normalised `facts`
object:

```json
{
  "status": "SUCCESS",
  "assessment_type": "membership_inference",
  "tool": "MIA service",
  "version": "0.0.9",
  "facts": { "shape": "parameterSweep", "worstSeverity": "HIGH", "...": "..." },
  "raw": { "status": "success", "version": "0.0.9", "data": "model_id;optim;lr;..." }
}
```

`version` is `MIA_SERVICE_VERSION`, pinned in `tools/mia_assessment.py` because the MIA service
service exposes no version endpoint to ask. It reaches reports as
`method.toolVersion` and `provenance.toolVersion`, alongside
`method.toolVersionSource: "pinned"` — the value describes the deployment this
checkout is configured against, not something the service reported, and it goes
stale silently if the MIA service is upgraded without editing that constant. **Do not write a
tool version into a report from anywhere else.** If the envelope has no `version`,
the field is omitted rather than filled: an invented version is a claim about
which build produced the evidence, and a reader cannot tell it from a real one.

The MIA service returns a parameter sweep as a semicolon-separated table — one row per
shadow-model configuration, with an attack advantage (`adv`) and an attacker
accuracy score (`score`) per row. `tools/mia_normalizer.py` parses that table
deterministically into metric observations, classifies each against the
severity thresholds declared in the ontology, derives findings from the
observations that cross a threshold, and records what the sweep did not cover.

**Do not parse the sweep table yourself, and do not recompute any figure in
`facts`.** Every number and severity in the report must come from `facts`
verbatim. Three properties of this tool's output make hand-reading it unsafe:

- `score` is an exact algebraic restatement of `adv` (`score = (1 - |adv|) /
  2`), not an independent measurement, and it moves *inversely* — a lower
  score is a worse outcome. A score of 0.43 is not "close to 0.5, therefore
  resilient"; it encodes an advantage of 0.136.
- The result is a sweep, so its central tendency is not its verdict. A single
  configuration crossing a threshold is a finding even when most
  configurations pass.
- **The severity thresholds are confirmed; the reading of `adv` is not.** The
  0.10 / 0.05 / 0.02 boundaries have been confirmed with the team that owns the
  attack implementation, so `facts.method.thresholdsConfirmed` is now true and no
  threshold caveat is emitted. What that confirmation did *not* settle is whether
  the sign of `adv` is directional or is noise around zero. Classification uses
  the absolute value — the conservative reading, which counts a negative
  advantage as a leak of the same size — so a finding resting on a negative value
  may be overstated if the sign turns out to be noise.
  `facts.method.provisionalMetricSemantics` records it and
  `facts.scopeLimitations` states it in prose. Carry it, and read
  `thresholdsConfirmed` and `metricSemanticsConfirmed` as the separate claims
  they are: neither stands for the other. The caveat applies to a clean result
  too, which is the claim that every value read as below those boundaries.

Report the worst configuration and where it occurs, carry every
`scopeLimitations` entry into the report, and keep the sign of an advantage as
directional information rather than treating a negative value as safe.
