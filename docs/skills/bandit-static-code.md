---
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
parses JSON output, summarizes severity counts, and returns a structured
assessment report.

## Output

Return a TM Forum aligned report with the intent ID, lifecycle status,
assessment type, tool name, execution time, issue summary, assessment verdict,
explanation, and recommendations.
