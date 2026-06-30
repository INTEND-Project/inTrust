---
name: formal-intent-generation
description: Generates a formal TM Forum intent JSON from a natural-language description, grounded in the InTrust ontology.
---

# Formal TM Forum Intent Generation

Use this skill when the user describes a trustworthiness assessment in natural
language and wants a formal TM Forum intent JSON in return — for example
"draft an intent that asks for a privacy assessment of model X before
deployment to edge node Y" or "produce the formal intent for a static-code
review of repo Z".

Do **not** use this skill to actually run an assessment — it only produces the
intent document. Execution is the job of the matching assessment skill (e.g.
`mia-privacy`, `bandit-static-code`).

## Inputs

The skill takes a single parameter:

- `description` — the user's natural-language description of the desired
  intent (free text). Optional fields the caller may also pass through:
  `requestedBy`, `targetHint`, `criteria`, `dueBy`.

Example invocation payload:

```json
{
  "description": "Pre-deployment privacy assessment for model-pm-v2 against membership inference, on edge node edge-ld-01.",
  "requestedBy": { "organization": "Fill GmbH", "contact": "ops@fill.example.com" }
}
```

## Execution

This skill is exposed to the agent as the `formal_intent_generation` tool,
which takes a single string argument named `description`:

- Pass the user's natural-language description as a plain string, **or**
- Pass a JSON object encoded as a string to include the optional pass-through
  fields:

```json
{
  "description": "<user's natural-language intent description>",
  "requestedBy": { },
  "targetHint":  "",
  "criteria":    [ ],
  "dueBy":       ""
}
```

The backing Python tool (`tools.formal_intent_generation.build_formal_intent`)
loads the InTrust ontology from `docs/skills/ontology/intrust.ttl` and returns
the ontology fragments (classes, properties, domains/ranges) relevant to intent
authoring, together with the user's description.

**Place the Turtle file at that path** — the tool fails with a clear error if
it is missing.

## Output

The tool returns:

```json
{
  "status": "SUCCESS",
  "description": "<echoed user description>",
  "ontology": {
    "classes":    [ { "iri": "...", "label": "...", "comment": "..." }, ... ],
    "properties": [ { "iri": "...", "label": "...", "domain": "...", "range": "...", "kind": "object|datatype" }, ... ]
  },
  "instructions": "Compose a TM Forum intent JSON using the classes/properties above ..."
}
```

After receiving this output, **compose** a complete TM Forum intent JSON
using the ontology classes and properties as the authoritative vocabulary.
The intent must include at least:

- `intentId` (generate a new id, e.g. `intent-<short-uuid>`)
- `intentType` (mapped from an ontology class)
- `description` (the user's description, lightly normalised)
- `target` — the asset under assessment
- `assessment` — `focus`, `assessmentType`, `parameters`
- `criteria` — any compliance/policy references the user mentioned
- `output` — desired report shape, defaulting to `tmfIntentReport.v1`
- `lifecycle.state = "Created"`

Prefer ontology IRIs over free strings where the ontology defines a term.
If the user's description is missing information that the ontology marks as
required, ask one clarifying question rather than inventing values.

## Required follow-up: SHACL validation

**You MUST validate the composed intent before presenting it to the user.**
Do not show the intent to the user until validation has run.

After composing the intent, immediately call the `formal_intent_validation`
tool, passing the composed intent JSON (serialized as a string) as its
`intent` argument.

Then:

- If `conforms == true` → present the validated intent JSON to the user and
  state that it conforms to the InTrust SHACL shapes.
- If `conforms == false` → fix the violations listed in `violations[]` and
  re-validate. After up to 2 repair attempts, if violations remain, present
  the latest intent **together with** the remaining violations and ask the
  user how to resolve them. Do not silently drop violations.

Only skip validation if the user has explicitly said "skip validation" or
the `formal-intent-validation` skill returns `status == "FAILED"` because
the SHACL shapes file is missing — in that case, present the intent and
warn the user that validation could not run.
