---
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
      "path": "/data/model.pt"
    },
    "shadowData": {
      "type": "synthetic"
    }
  }
}
```

The expected parameters are `parameters.model` and `parameters.shadowData`.

## Execution

Run the `run_mia_assessment` implementation. It performs the membership
inference assessment workflow and returns model privacy metrics.

## Output

Return a TM Forum aligned report with the intent ID, lifecycle status, model
privacy metrics, assessment verdict, explanation, and recommendations.
