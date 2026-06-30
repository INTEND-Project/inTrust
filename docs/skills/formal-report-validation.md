---
name: formal-report-validation
description: Validates a TM Forum assessment report against the InTrust SHACL shapes and returns conformance violations.
---

# Formal TM Forum Report Validation

Use this skill **after** generating or receiving a TM Forum assessment
report, to check that it conforms to the InTrust ontology's SHACL shapes.
Typical triggers:

- You have just composed a report via `formal-report-generation` and want
  to verify it before presenting it to the user.
- The user pastes a TMF report JSON and asks for review.

This skill does **not** run the assessment — it only checks the report shape
against the ontology.

## Inputs

This skill is exposed to the agent as the `formal_report_validation` tool,
which takes a single string argument named `report`. That string is either:

- a TM Forum report **JSON** document, e.g.
  `{ "intentId": "intent-123", "reportType": "...", "...": "..." }`, or
- a **Turtle** (RDF) serialization, e.g.
  `@prefix : <...> . :report-123 a :PrivacyAssessmentReport ; ...`

The skill detects which form was passed and routes JSON to the validator's
`report` payload and Turtle to its `report_ttl` payload.

To override the JSON-LD `context` or the SHACL `shapes_ttl_path`, pass a JSON
object string of the form
`{ "report": { ... }, "context": { ... }, "shapes_ttl_path": "..." }`:

- `context` — JSON-LD context to apply to the JSON report. If omitted, the
  tool wraps the report in a default context with `@vocab` set to the
  ontology base IRI.
- `shapes_ttl_path` — override the SHACL shapes file path. Defaults to
  `docs/skills/ontology/intrust-shapes.ttl`, falling
  back to `intrust.ttl`.

## Execution

The backing Python tool
(`tools.formal_report_validation.validate_formal_report`) reuses the
shape-agnostic SHACL validator from `tools.formal_intent_validation`.

## Output

```json
{
  "status": "SUCCESS",
  "conforms": true,
  "violation_count": 0,
  "violations": [],
  "report_text": "Validation Report\nConforms: True\n..."
}
```

When `conforms` is false, `violations` lists each focus node, the failing
shape, the property path, and the human-readable message. Use those to fix
the report and re-validate.
