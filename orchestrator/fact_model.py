# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Canonical fact model for assessment results.

Every assessment skill produces raw tool output in its own shape: Bandit and
Trivy emit a list of findings, the membership-inference (MIA) service emits a
parameter sweep as semicolon-separated rows.  This module defines the single
shape those raw results are normalised into, so that reporting reads one
object regardless of which tool ran.

Why this exists
---------------
Report composition used to hand the raw result to an LLM together with the
instruction to "parse unstructured raw_result content (CSV, free text) into
the metrics named by the ontology".  Asking a model to both parse numbers and
interpret them means the numbers in a report are not traceable to the tool
output.  On the MIA sweep it also misread the result: every stored narrative
concluded "scores consistently around 0.49-0.50, high resilience", while the
attack advantage in the same rows spanned 0.003 to 0.136, concentrated in one
corner of the parameter grid.

So extraction is deterministic Python and lives here.  Severity is not
decided here either: it is derived from the ``spa:Threshold`` individuals
declared in the ontology (see ``threshold_registry``).  The model's remaining
job is language, not arithmetic.

Result shapes
-------------
``findingList``
    Bandit, Trivy.  Discrete findings, each already carrying a severity from
    the tool.  Reporting reduces these by selection (top-N, severity floor).

``parameterSweep``
    MIA service membership inference.  One metric observed repeatedly across a grid
    of input parameters.  Reporting reduces these by aggregation (worst case,
    worst per dimension), because dropping rows from a sweep destroys the
    comparison that *is* the result.

Both shapes populate the same ``FactModel``; a normalizer fills in whichever
of ``findings`` / ``observations`` its tool produces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Severity ordering, ascending.  Used to rank derived severities and to
# compare against a profile's severity floor.  Mirrors the ``spa:Severity``
# individuals in the ontology.
SEVERITY_ORDER = ("NONE", "LOW", "MEDIUM", "HIGH", "CRITICAL")


def severity_rank(severity: Optional[str]) -> int:
    """Return the ordinal of a severity label, or 0 when unknown."""
    if not severity:
        return 0
    try:
        return SEVERITY_ORDER.index(severity.strip().upper())
    except ValueError:
        return 0


@dataclass(frozen=True)
class Observation:
    """
    One metric value measured under one combination of input parameters.

    ``dimensions`` are the swept parameters (learning rate, batch size,
    optimiser).  They are deliberately *not* treated as a unique key: the
    observed MIA output repeats one grid cell, and that replicate is useful
    signal about measurement noise rather than a defect to deduplicate away.

    ``severity`` is filled in by threshold classification, not by the tool.
    """

    metric: str
    value: float
    unit: Optional[str] = None
    dimensions: Dict[str, Any] = field(default_factory=dict)
    # Identifier of the individual measured entity, when the tool reports one
    # (the MIA service gives a per-shadow-model id).
    subject: Optional[str] = None
    severity: Optional[str] = None
    # The ontology threshold individual that produced ``severity``, so a
    # report can cite why an observation was classified as it was.
    classified_by: Optional[str] = None


@dataclass(frozen=True)
class Finding:
    """
    One discrete assessment finding.

    The three detail tiers are separate fields rather than three phrasings of
    the same text, so that an audience projection is a field selection and
    cannot restate the finding differently for different readers.
    """

    title: str
    severity: str
    # Plain-language consequence, for management and non-technical readers.
    business_impact: Optional[str] = None
    # Tool-level specifics: rule id, CWE, location, confidence.
    technical_detail: Dict[str, Any] = field(default_factory=dict)
    # Substantiation: raw snippet, source reference, tool output pointer.
    evidence: Dict[str, Any] = field(default_factory=dict)
    remediation: Dict[str, Any] = field(default_factory=dict)
    # Observations that justify this finding, mirroring
    # ``spa:findingBasedOnMetric``.  Present for findings derived from metric
    # thresholds; empty for findings a tool reported directly.
    based_on: List[Observation] = field(default_factory=list)


@dataclass(frozen=True)
class MetricSummary:
    """
    Aggregate of all observations of one metric.

    Computed once here so that every audience projection quotes the same
    aggregate rather than recomputing (or re-estimating) its own.
    """

    metric: str
    unit: Optional[str]
    count: int
    worst_value: float
    worst_dimensions: Dict[str, Any]
    best_value: float
    median_value: float
    # True when a larger value is the worse outcome.  Read from the ontology
    # rather than assumed, because privacy metric polarity varies.
    higher_is_worse: bool = True
    # Set when this metric is an algebraic restatement of another, so
    # reporting does not present it as independent corroboration.
    derived_from: Optional[str] = None
    derivation_expression: Optional[str] = None


@dataclass(frozen=True)
class FactModel:
    """
    The normalised, tool-independent result of one assessment.

    This is the single object every audience-specific rendition is projected
    from.  Two renditions cannot disagree about what was measured, because
    they read the same instance.
    """

    shape: str  # "findingList" | "parameterSweep"
    skill: str
    status: str  # SUCCESS | FAILED | INCONCLUSIVE
    observations: List[Observation] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    metric_summaries: List[MetricSummary] = field(default_factory=list)
    # Stated boundaries of the assessment: grid cells not exercised,
    # degenerate inputs, attack classes not attempted.  Surfaced rather than
    # dropped, because for a compliance reader the untested surface matters as
    # much as the findings.
    scope_limitations: List[str] = field(default_factory=list)
    # The same boundaries, phrased for a reader outside the organisation.
    #
    # Separate from ``scope_limitations`` rather than derived from it, because
    # the internal phrasing names the things that make a limitation checkable —
    # file paths, swept parameter values, model identifiers — and those are
    # exactly what must not leave.  A normalizer opts in by writing wording it is
    # willing to have quoted to a customer; one that writes none withholds the
    # external statement rather than having its internal prose reused.  This
    # mirrors ``EXTERNAL_ALLOWLIST``: silence omits, it does not leak.
    external_scope_statement: List[str] = field(default_factory=list)
    # Sweep configuration, tool endpoint, and similar execution context.
    method: Dict[str, Any] = field(default_factory=dict)
    # Which criteria the intent named, and which of them this skill can
    # actually evidence (see ``orchestrator.criterion_registry``).  Resolved
    # deterministically rather than described by the report-composing model,
    # because "we assessed GDPR" is a claim about the framework's capabilities
    # rather than a phrasing choice.
    regulatory_coverage: Dict[str, Any] = field(default_factory=dict)
    # Set when normalisation could not fully interpret the raw output.  A
    # normalizer degrades to a partial FactModel rather than raising, so a
    # successful assessment is never lost to a parsing problem.
    normalization_error: Optional[str] = None

    @property
    def worst_severity(self) -> str:
        """The highest severity present across findings and observations."""
        ranks = [severity_rank(f.severity) for f in self.findings]
        ranks += [severity_rank(o.severity) for o in self.observations]
        return SEVERITY_ORDER[max(ranks)] if ranks else "NONE"

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for storage in the report envelope and for the API."""
        return {
            "shape": self.shape,
            "skill": self.skill,
            "status": self.status,
            "worstSeverity": self.worst_severity,
            "observations": [
                {
                    "metric": o.metric,
                    "value": o.value,
                    "unit": o.unit,
                    "dimensions": o.dimensions,
                    "subject": o.subject,
                    "severity": o.severity,
                    "classifiedBy": o.classified_by,
                }
                for o in self.observations
            ],
            "findings": [
                {
                    "title": f.title,
                    "severity": f.severity,
                    "businessImpact": f.business_impact,
                    "technicalDetail": f.technical_detail,
                    "evidence": f.evidence,
                    "remediation": f.remediation,
                    "basedOn": [
                        {
                            "metric": o.metric,
                            "value": o.value,
                            "dimensions": o.dimensions,
                            "subject": o.subject,
                        }
                        for o in f.based_on
                    ],
                }
                for f in self.findings
            ],
            "metricSummaries": [
                {
                    "metric": m.metric,
                    "unit": m.unit,
                    "count": m.count,
                    "worstValue": m.worst_value,
                    "worstDimensions": m.worst_dimensions,
                    "bestValue": m.best_value,
                    "medianValue": m.median_value,
                    "higherIsWorse": m.higher_is_worse,
                    "derivedFrom": m.derived_from,
                    "derivationExpression": m.derivation_expression,
                }
                for m in self.metric_summaries
            ],
            "scopeLimitations": self.scope_limitations,
            "externalScopeStatement": self.external_scope_statement,
            "method": self.method,
            "regulatoryCoverage": self.regulatory_coverage,
            "normalizationError": self.normalization_error,
        }
