---
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

The skill invokes the packaged Trivy binary with filesystem scanners
enabled and returns summarized findings.

## Output

Return a TM Forum aligned report with the intent ID, lifecycle status,
assessment type, target path, tool metadata, metrics, assessment verdict, and
explanation.
