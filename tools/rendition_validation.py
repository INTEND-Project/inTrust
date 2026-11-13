# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
SHACL validation for audience renditions.

Until now only the composed formal report was validated, which left the
artifacts people actually read unchecked.  A rendition is produced by
``orchestrator/report_profile.py`` and is pure field selection over the
canonical fact model, so most of what could go wrong is a projection bug rather
than a bad measurement — and the projection bugs that matter are exactly the
ones a shape can state: an external statement released without its scope, a
reduced rendition that drops findings without saying so, a confidential view
claiming external disclosure.

Two design points.

*The shapes are not a second implementation of the gate.*  ``project_external``
decides whether to release; ``spa:ExternalStatementShape`` asserts that whatever
reached the graph is internally consistent.  A rendition that arrived by some
path other than ``project()`` — hand-edited, restored from an older store,
re-projected by a future caller — is still checked.  The duplication is the
point: a gate enforced in one function is only as good as the callers that go
through it.

*Validation never changes the rendition and never raises.*  It returns a
verdict alongside it.  A conformance failure means the projection is suspect, so
discarding the rendition on the strength of it would destroy the evidence needed
to diagnose the projection; and an assessment that ran must not be lost to a
validator problem.  ``validate_rendition`` therefore reports ``status:
"FAILED"`` for its own errors, distinct from ``conforms: False`` for a rendition
that really does violate a shape.

The JSON-LD mapping is explicit rather than a blanket ``@vocab``.  The
``@vocab`` shortcut is what makes the intent validator wrongly type nodes (see
the comment in ``formal_intent_validation``), and here it would be worse: an
unmapped key silently contributes no triples, so a shape asserting
``sh:minCount 1`` on a field the rendition *does* carry would fail for the wrong
reason.  Unmapped keys go to a neutral namespace with no domain or range.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from . import formal_intent_validation

SPA = "https://intend-project.eu/ontology/spa#"
NEUTRAL = "urn:intrust:rendition:"

# Rendition field -> ontology property.  Only the fields the shapes constrain
# are mapped; everything else reaches the graph under ``NEUTRAL`` where no shape
# targets it, which is the intended behaviour rather than an omission — a
# rendition carries audience content that the shapes have no opinion about.
_PROFILE_FIELDS = {
    "name": "spa:renditionProfile",
    "resolvedBy": "spa:renditionResolvedBy",
    "numericDisclosure": "spa:numericDisclosure",
    "canonicalWorstSeverity": "spa:canonicalWorstSeverity",
    "canonicalFindingCount": "spa:canonicalFindingCount",
    "findingsOmitted": "spa:findingsOmitted",
    "requiresApprovalBeforeRelease": "spa:requiresApprovalBeforeRelease",
    "approvalState": "spa:approvalState",
    "approvedBy": "spa:approvedBy",
    "approvalRecordedAt": "spa:approvalRecordedAt",
    "approvalReference": "spa:approvalReference",
    "validityPeriod": "spa:statementValidityPeriod",
}

# Dates live at the top level of an external statement rather than under
# ``reportProfile``: they are part of what the statement asserts, not of how it
# was produced, and the allowlist admits them for that reason.
_STATEMENT_FIELDS = {
    "assessedOn": "spa:assessedOn",
    "validUntil": "spa:statementValidUntil",
}

_DISCLOSURE_INDIVIDUALS = {
    "internal": "spa:DisclosureInternal",
    "confidential": "spa:DisclosureConfidential",
    "external": "spa:DisclosureExternal",
}

_CONTEXT = {
    "@vocab": NEUTRAL,
    "spa": SPA,
    "renditionProfile": "spa:renditionProfile",
    "renditionResolvedBy": "spa:renditionResolvedBy",
    "numericDisclosure": "spa:numericDisclosure",
    "canonicalWorstSeverity": "spa:canonicalWorstSeverity",
    "canonicalFindingCount": {"@id": "spa:canonicalFindingCount", "@type": "xsd:integer"},
    "findingsOmitted": {"@id": "spa:findingsOmitted", "@type": "xsd:integer"},
    "disclosureClass": {"@id": "spa:disclosureClass", "@type": "@id"},
    "renditionReleased": {"@id": "spa:renditionReleased", "@type": "xsd:boolean"},
    "withheldBecause": "spa:withheldBecause",
    "externalScopeStatement": "spa:externalScopeStatement",
    # Typed rather than left as strings: the shapes compare an expiry against an
    # assessment date, and an untyped literal comparison would be lexical — so
    # "2026-1-5" would sort after "2026-11-04" and the expiry check would pass
    # on a statement that had in fact expired.
    "assessedOn": {"@id": "spa:assessedOn", "@type": "xsd:dateTime"},
    "statementValidUntil": {
        "@id": "spa:statementValidUntil", "@type": "xsd:dateTime"
    },
    "statementValidityPeriod": {
        "@id": "spa:statementValidityPeriod", "@type": "xsd:duration"
    },
    "requiresApprovalBeforeRelease": {
        "@id": "spa:requiresApprovalBeforeRelease", "@type": "xsd:boolean"
    },
    "approvalState": "spa:approvalState",
    "approvedBy": "spa:approvedBy",
    "approvalRecordedAt": {
        "@id": "spa:approvalRecordedAt", "@type": "xsd:dateTime"
    },
    "approvalReference": "spa:approvalReference",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}


def _as_document(rendition: Dict[str, Any]) -> Dict[str, Any]:
    """
    Lift the fields the shapes constrain out of a rendition into a flat node.

    The reconciliation figures live under ``reportProfile`` in a rendition but
    are properties of the rendition itself in the ontology, so they are hoisted
    rather than nested.  Nesting them would put them on an anonymous child node
    that no shape targets, and the validation would pass vacuously — the failure
    mode this module exists to prevent.
    """
    profile = rendition.get("reportProfile")
    profile = profile if isinstance(profile, dict) else {}

    document: Dict[str, Any] = {}
    for source, mapped in _PROFILE_FIELDS.items():
        if source in profile and profile[source] is not None:
            document[mapped.split(":", 1)[1]] = profile[source]

    disclosure = str(profile.get("disclosureClass") or "").lower()
    individual = _DISCLOSURE_INDIVIDUALS.get(disclosure)
    if individual:
        document["disclosureClass"] = individual

    is_external = disclosure == "external"
    if is_external:
        # ``released`` is the external path's own field and is absent from
        # internal renditions; a missing value is not defaulted, so that the
        # shape's minCount reports it rather than this module inventing False.
        if "released" in rendition:
            document["renditionReleased"] = bool(rendition["released"])
        for source, target in (
            ("withheldBecause", "withheldBecause"),
            ("scopeStatement", "externalScopeStatement"),
        ):
            values = rendition.get(source)
            if isinstance(values, list) and values:
                document[target] = [str(value) for value in values]
        # The validity dates.  Absent values are not defaulted, for the same
        # reason as ``released``: the shape must be able to report a released
        # statement that carries no expiry, and a default invented here would
        # hide exactly that.
        for source, mapped in _STATEMENT_FIELDS.items():
            value = rendition.get(source)
            if value:
                document[mapped.split(":", 1)[1]] = str(value)

    document["@type"] = (
        "spa:ExternalStatement" if is_external else "spa:ReportRendition"
    )
    document["@context"] = _CONTEXT
    return document


def validate_rendition(
    rendition: Dict[str, Any], shapes_ttl_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate one audience rendition against the InTrust SHACL shapes.

    Returns ``{status, conforms, violation_count, violations, ...}``.  ``status``
    describes the validator; ``conforms`` describes the rendition.  A rendition
    that failed to project at all (``{"error": ...}``) is reported as skipped
    rather than as non-conformant: there is no artifact to validate, and calling
    it a shape violation would misattribute the failure.
    """
    if not isinstance(rendition, dict):
        return {"status": "FAILED", "error": "rendition must be a JSON object"}
    if "error" in rendition and "reportProfile" not in rendition:
        return {
            "status": "SKIPPED",
            "reason": "projection failed, so there is no rendition to validate",
            "projectionError": str(rendition["error"]),
        }

    try:
        document = _as_document(rendition)
    except Exception as error:  # noqa: BLE001
        return {"status": "FAILED", "error": f"failed to build data graph: {error}"}

    payload: Dict[str, Any] = {
        "intent": document,
        "context": document.pop("@context"),
    }
    if shapes_ttl_path:
        payload["shapes_ttl_path"] = shapes_ttl_path

    result = formal_intent_validation.validate_formal_intent(payload)
    # The delegate reports on an "intent"; relabel so a reader of the stored
    # envelope is not told an intent was validated when a rendition was.
    result["validated"] = "rendition"
    result["renditionProfile"] = (rendition.get("reportProfile") or {}).get("name")
    return result


def validate_renditions(
    renditions: Dict[str, Dict[str, Any]], shapes_ttl_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validate several renditions and summarise.

    ``allConform`` is false if any rendition violates a shape.  A skipped or
    failed validation does not make it false — those are not statements about
    the renditions — but they are counted separately so a caller cannot read
    ``allConform: true`` as "every rendition was checked".
    """
    results: Dict[str, Any] = {}
    for name, rendition in (renditions or {}).items():
        results[name] = validate_rendition(rendition, shapes_ttl_path)

    checked = [r for r in results.values() if r.get("status") == "SUCCESS"]
    violations: List[str] = [
        name
        for name, result in results.items()
        if result.get("status") == "SUCCESS" and not result.get("conforms")
    ]
    return {
        "allConform": not violations,
        "checkedCount": len(checked),
        "notCheckedCount": len(results) - len(checked),
        "nonConforming": violations,
        "byProfile": results,
    }
