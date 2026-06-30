---
name: formal-report-generation
description: Generates a formal TM Forum assessment report (tmfIntentReport.v1) from a raw assessment result, grounded in the InTrust ontology.
---

# Formal TM Forum Report Generation

Use this skill **after any assessment skill** (e.g. `mia-privacy`,
`bandit-static-code`, `trivy-docker-image`, `trivy-filesystem`,
`trivy-kubernetes`) has returned a raw result, to produce a TM Forum-aligned
report grounded in the InTrust ontology.

Do **not** use this skill to run the assessment itself — it only shapes the
result into a formal report.

## Inputs

This skill is exposed to the agent as the `formal_report_generation` tool,
which takes a single string argument named `reportInput`. Because report
generation needs both the original intent and the raw assessment result, pass
a JSON object encoded as a string:

```json
{
  "intent":     { },
  "raw_result": { },
  "report_class": "PrivacyAssessmentReport"
}
```

- `intent` — the original TM Forum intent JSON.
- `raw_result` — whatever the assessment skill returned.
- `report_class` — optional ontology class hint. If omitted, the tool falls
  back to the `report_class` field in the executed skill's `metadata.json`
  (when present) or returns the full set of ontology report classes for the
  LLM to pick from.

## Execution

The backing Python tool
(`tools.formal_report_generation.build_formal_report`) loads the InTrust
ontology from `docs/skills/ontology/intrust.ttl` and
returns the report-relevant ontology fragments together with the intent and
raw result.

## Output

```json
{
  "status": "SUCCESS",
  "intent": { ... },
  "raw_result": { ... },
  "ontology": {
    "report_classes": [ { "iri": "...", "label": "...", "comment": "..." }, ... ],
    "report_properties": [ { "iri": "...", "label": "...", "domain": "...", "range": "...", "kind": "object|datatype" }, ... ]
  },
  "selected_report_class": "PrivacyAssessmentReport",
  "instructions": "Compose a tmfIntentReport.v1 JSON using the classes/properties above ..."
}
```

After receiving this output, **compose** a complete TM Forum report JSON
using the ontology classes and properties as the authoritative vocabulary.
The report must include at least:

- `intentId` (carried over from the input intent)
- `reportType` (mapped from an ontology report class, e.g.
  `tmfIntentReport.v1`)
- `status` — terminal state of the assessment (`SUCCESS` / `FAILED` /
  `INCONCLUSIVE`)
- `summary` — short human-readable verdict
- `findings` — structured list, each item using ontology properties for its
  fields (severity, metric, value, …)
- `recommendations` — list of remediations, if applicable
- `provenance` — `{ "skillId": ..., "executedAt": ..., "rawResultRef": ... }`
- `lifecycle.state = "Completed"` (or `"Failed"`)

Map raw result fields onto ontology properties wherever possible. If the
raw result is unstructured (CSV, free text), parse out the key metrics
named by the ontology before composing — never paste raw blobs into a
property whose range is a datatype like `xsd:decimal`.

## Required follow-up: SHACL validation

**You MUST validate the composed report before presenting it to the user.**
Do not show the report to the user until validation has run.

After composing the report, immediately call the `formal_report_validation`
tool, passing the composed report JSON (serialized as a string) as its
`report` argument.

Then:

- If `conforms == true` → present the validated report to the user and state
  that it conforms to the InTrust SHACL shapes.
- If `conforms == false` → fix the violations listed in `violations[]` and
  re-validate. After up to 2 repair attempts, if violations remain, present
  the latest report **together with** the remaining violations and ask the
  user how to resolve them.

Only skip validation if the user has explicitly said "skip validation" or
the `formal-report-validation` skill returns `status == "FAILED"` because
the SHACL shapes file is missing — in that case, present the report and
warn the user that validation could not run.
