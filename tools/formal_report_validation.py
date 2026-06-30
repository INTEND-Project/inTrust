"""Tool backing the `formal-report-validation` skill.

The validator in `formal_intent_validation` is already shape-agnostic — it
validates an arbitrary RDF graph against an arbitrary SHACL shapes graph.
This module is a thin adapter that accepts a `report` (or `report_ttl`)
payload, normalises it to the validator's expected `intent` / `intent_ttl`
keys, and delegates.
"""

from typing import Any, Dict

from . import formal_intent_validation


def validate_formal_report(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a TM Forum assessment report against the InTrust SHACL shapes.

    Expected payload:
        {
            "report":     {...}          | "report_ttl": "@prefix ...",
            "context":    {...},         # optional JSON-LD context override
            "shapes_ttl_path": "..."     # optional override
        }
    """
    if "report" not in payload and "report_ttl" not in payload:
        return {
            "status": "FAILED",
            "error": "payload must contain either 'report' or 'report_ttl'",
        }

    delegated: Dict[str, Any] = {}
    if "report" in payload:
        report = payload["report"]
        # The SHACL AssessmentReportShape targets spa:AssessmentReport. The
        # validator only types JSON nodes from an explicit @type, so without
        # one the report node is untyped and targetClass matches nothing
        # (validation would pass vacuously). Inject the type unless the caller
        # already supplied one.
        if isinstance(report, dict) and "@type" not in report and "type" not in report:
            report = {**report, "@type": "AssessmentReport"}
        delegated["intent"] = report
    if "report_ttl" in payload:
        delegated["intent_ttl"] = payload["report_ttl"]
    for passthrough in ("context", "shapes_ttl_path"):
        if passthrough in payload:
            delegated[passthrough] = payload[passthrough]

    return formal_intent_validation.validate_formal_intent(delegated)
