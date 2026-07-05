---
description: Scans Docker images for high and critical vulnerabilities using Trivy.
---

# Trivy Docker Image Security Assessment

Use this skill when the intent asks to scan a container image, Docker image, or
containerized application for known vulnerabilities.

## Inputs

Expected TM Forum intent shape:

```json
{
  "intentId": "intent-001",
  "parameters": {
    "dockerImage": "python:3.11-slim"
  }
}
```

The required parameter is `parameters.dockerImage`.

## Execution

The skill invokes the packaged Trivy binary, scans the image, parses the
JSON output, and summarizes findings.

## Output

Return a TM Forum aligned report with the intent ID, lifecycle status,
assessment type, target image, tool metadata, metrics, assessment verdict, and
explanation.
