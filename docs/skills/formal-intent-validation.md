---
name: formal-intent-validation
description: Validates a TM Forum intent against the InTrust SHACL shapes and returns conformance violations.
---

# Formal TM Forum Intent Validation

Use this skill **after** generating or receiving a TM Forum intent, to check
that it conforms to the InTrust ontology's SHACL shapes. Typical triggers:

- The user asks "is this intent valid?" or "validate this intent".
- You have just composed an intent via `formal-intent-generation` and want to
  verify it before handing it to the matching assessment skill.
- The user pastes a TMF intent JSON and asks for review.

This skill does **not** execute the assessment — it only checks the intent
shape against the ontology.

## Inputs

This skill is exposed to the agent as the `formal_intent_validation` tool,
which takes a single string argument named `intent`. That string is either:

- a TM Forum intent **JSON** document, e.g.
  `{ "intentId": "intent-123", "intentType": "...", "...": "..." }`, or
- a **Turtle** (RDF) serialization, e.g.
  `@prefix : <...> . :intent-123 a :PrivacyAssessmentIntent ; ...`

The skill detects which form was passed and routes JSON to the validator's
`intent` payload and Turtle to its `intent_ttl` payload.

To override the JSON-LD `context` or the SHACL `shapes_ttl_path`, pass a JSON
object string of the form
`{ "intent": { ... }, "context": { ... }, "shapes_ttl_path": "..." }`:

- `context` — JSON-LD context to apply to the JSON intent. If omitted, the
  tool wraps the intent in a default context with `@vocab` set to the
  ontology base IRI, so plain TMF JSON keys resolve against the ontology.
- `shapes_ttl_path` — override the SHACL shapes file path. Defaults to
  `docs/skills/ontology/intrust-shapes.ttl`, falling
  back to `intrust.ttl` (shapes may live alongside the ontology).

## Execution

The backing Python tool (`tools.formal_intent_validation.validate_formal_intent`)
loads the SHACL shapes graph and validates the intent using `pyshacl`. JSON
intents are converted to RDF via JSON-LD; Turtle intents are parsed directly.

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
shape, the property path, and the human-readable message from the SHACL
report. Use those to either fix the intent and re-validate, or to ask the
user the minimal clarifying question needed to resolve the violation.
