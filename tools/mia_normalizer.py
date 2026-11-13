# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Deterministic normaliser for MIA membership-inference results.

The MIA service returns a parameter sweep as a semicolon-separated table
inside a JSON envelope::

    {"status": "success", "data":
     "model_id;optim;lr;batch_size;train_acc;test_acc;adv;score\\n
      821...ae1;adam;0.5;64;1.0;1.0;-0.0032;0.4984\\n
      ..."}

This module turns that into a ``FactModel``: one ``Observation`` per row,
severity derived from the ontology thresholds, findings derived from the
observations that cross them, and scope limitations for what the sweep did
not establish.

Why the parsing is here and not in a prompt
-------------------------------------------
Report composition previously asked the LLM to parse this table itself.  On
the observed payload that produced three separate narratives all concluding
"scores consistently around 0.49-0.50 ... high resilience, no significant
leakage", when in the same rows the attack advantage reached 0.136 -- twelve
times the median -- concentrated entirely in the ``lr=0.1, batch_size=32``
corner for both optimisers.  The reduction that matters in a sweep is the
worst case and its location; a model summarising row text is prone to
reporting the central tendency instead.

Three properties of the observed output shape this module:

``score`` is not an independent metric
    ``score == (1 - abs(adv)) / 2`` holds exactly for every observed row.  It
    is recorded for traceability but marked as derived, so reporting will not
    present it as a second, corroborating measurement.  Note also that it
    moves *inversely*: a lower score is a worse outcome.

Dimensions are not a unique key
    The observed sweep has 13 rows over 12 grid cells; ``adam/lr=0.5/bs=128``
    appears twice, with advantages 0.0088 and 0.0128.  That replicate is a
    measurement-noise estimate, so rows are never keyed or deduplicated by
    their dimensions.

The sign of ``adv`` is not settled
    The severity boundaries are confirmed with the MIA service team; whether the sign
    of the column is directional or is noise around zero is not.
    Classification compares the absolute value, the conservative reading, and
    the qualification is disclosed rather than resolved here — see
    ``_provisional_metric_semantics``.
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional, Tuple

from orchestrator.fact_model import (
    FactModel,
    Finding,
    MetricSummary,
    Observation,
    severity_rank,
)
from orchestrator.criterion_registry import coverage_for_intent
from orchestrator.threshold_registry import ThresholdRegistry, load_registry

SKILL_NAME = "mia-privacy"

# Raw MIA column -> ontology ``spa:metricIdentifier``.
_METRIC_COLUMNS = {
    "adv": "membershipInferenceAdvantage",
    "score": "membershipInferenceScore",
}

# Columns that identify the swept configuration rather than a measurement.
_DIMENSION_COLUMNS = ("optim", "lr", "batch_size")

# Columns describing the trained model's own accuracy.  Not privacy metrics,
# but relevant to whether the sweep is informative at all.
_ACCURACY_COLUMNS = ("train_acc", "test_acc")

_SUBJECT_COLUMN = "model_id"


def _coerce(value: str) -> Any:
    """Parse a cell into int or float when it looks numeric, else keep text."""
    text = value.strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def parse_sweep_table(data: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Parse the semicolon-separated sweep table.

    Returns ``(rows, problems)``.  Malformed rows are collected in
    ``problems`` rather than raised, so a partially readable table still
    yields the rows that were readable.
    """
    problems: List[str] = []
    lines = [line for line in (data or "").splitlines() if line.strip()]
    if not lines:
        return [], ["MIA service returned an empty result table"]

    header = [column.strip() for column in lines[0].split(";")]
    rows: List[Dict[str, Any]] = []
    for line_number, line in enumerate(lines[1:], start=2):
        cells = line.split(";")
        if len(cells) != len(header):
            problems.append(
                f"row {line_number} has {len(cells)} fields, expected "
                f"{len(header)}; row skipped"
            )
            continue
        rows.append(
            {key: _coerce(cell) for key, cell in zip(header, cells)}
        )
    return rows, problems


def _dimensions(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        column: row[column] for column in _DIMENSION_COLUMNS if column in row
    }


def _format_dimensions(dimensions: Dict[str, Any]) -> str:
    """Render a configuration for prose: ``optim=adam, lr=0.1, batch_size=32``."""
    return ", ".join(f"{key}={value}" for key, value in dimensions.items())


def _build_observations(
    rows: List[Dict[str, Any]], registry: ThresholdRegistry
) -> List[Observation]:
    observations: List[Observation] = []
    for row in rows:
        dimensions = _dimensions(row)
        subject = row.get(_SUBJECT_COLUMN)
        for column, metric_identifier in _METRIC_COLUMNS.items():
            if column not in row:
                continue
            raw_value = row[column]
            if not isinstance(raw_value, (int, float)):
                continue
            definition = registry.get(metric_identifier)
            severity, classified_by = (
                definition.classify(float(raw_value))
                if definition is not None
                else ("NONE", None)
            )
            # A derived metric restates another; classifying it too would
            # double-count the same underlying measurement.
            if definition is not None and definition.derived_from:
                severity, classified_by = "NONE", None
            observations.append(
                Observation(
                    metric=metric_identifier,
                    value=float(raw_value),
                    unit=definition.unit if definition else None,
                    dimensions=dimensions,
                    subject=str(subject) if subject is not None else None,
                    severity=severity,
                    classified_by=classified_by,
                )
            )
    return observations


def _summarise(
    observations: List[Observation], registry: ThresholdRegistry
) -> List[MetricSummary]:
    summaries: List[MetricSummary] = []
    metrics = sorted({observation.metric for observation in observations})
    for metric in metrics:
        group = [o for o in observations if o.metric == metric]
        definition = registry.get(metric)
        higher_is_worse = definition.higher_is_worse if definition else True

        # "Worst" follows the metric's declared polarity, and uses magnitude
        # for upper-bounded metrics where sign is directional only.
        def _severity_key(observation: Observation) -> float:
            return (
                abs(observation.value)
                if higher_is_worse
                else -observation.value
            )

        worst = max(group, key=_severity_key)
        best = min(group, key=_severity_key)
        summaries.append(
            MetricSummary(
                metric=metric,
                unit=definition.unit if definition else None,
                count=len(group),
                worst_value=worst.value,
                worst_dimensions=worst.dimensions,
                best_value=best.value,
                median_value=statistics.median(o.value for o in group),
                higher_is_worse=higher_is_worse,
                derived_from=definition.derived_from if definition else None,
                derivation_expression=(
                    definition.derivation_expression if definition else None
                ),
            )
        )
    return summaries


def _derive_findings(
    observations: List[Observation], registry: ThresholdRegistry
) -> List[Finding]:
    """
    Turn threshold-crossing observations into findings.

    Observations that cross the same threshold are grouped into one finding,
    so a report says "two configurations exceed the high-risk threshold"
    rather than repeating a near-identical finding per row.  The specific
    configurations stay attached via ``based_on``, so no detail is lost to the
    grouping -- only the audience projection decides how much of it to show.
    """
    findings: List[Finding] = []
    flagged = [
        observation
        for observation in observations
        if severity_rank(observation.severity) > 0
    ]
    if not flagged:
        return findings

    by_severity: Dict[str, List[Observation]] = {}
    for observation in flagged:
        by_severity.setdefault(observation.severity or "NONE", []).append(
            observation
        )

    for severity, group in sorted(
        by_severity.items(), key=lambda item: severity_rank(item[0]), reverse=True
    ):
        metric = group[0].metric
        definition = registry.get(metric)
        metric_label = (
            definition.label if definition and definition.label else metric
        )
        threshold_iri = group[0].classified_by
        threshold_value = next(
            (
                t.value
                for t in (definition.thresholds if definition else ())
                if t.iri == threshold_iri
            ),
            None,
        )
        worst = max(group, key=lambda o: abs(o.value))
        configurations = [_format_dimensions(o.dimensions) for o in group]

        title = (
            f"{metric_label} reaches {abs(worst.value):.4f} at "
            f"{_format_dimensions(worst.dimensions)}"
        )
        if len(group) > 1:
            title += f" ({len(group)} configurations affected)"

        findings.append(
            Finding(
                title=title,
                severity=severity,
                business_impact=(
                    "An attacker able to query the model in this configuration "
                    "could determine whether a specific record was part of the "
                    "training data more reliably than by guessing. Where the "
                    "training data is personal data, that inference is itself a "
                    "disclosure."
                ),
                technical_detail={
                    "metric": metric,
                    "worstValue": worst.value,
                    "worstConfiguration": worst.dimensions,
                    "affectedConfigurations": configurations,
                    "observationCount": len(group),
                    "thresholdValue": threshold_value,
                    "thresholdIri": threshold_iri,
                },
                evidence={
                    "subjects": [o.subject for o in group if o.subject],
                    "values": [o.value for o in group],
                    "sourceColumn": "adv",
                },
                remediation={
                    "oneLine": (
                        "Avoid the affected training configurations, or apply "
                        "a privacy-preserving training method before release."
                    ),
                    "steps": [
                        "Re-train the affected configurations with "
                        "differentially private optimisation, or exclude them "
                        "from the deployment candidate set.",
                        "Confirm the chosen configuration's advantage stays "
                        "below the high-risk threshold on a re-run.",
                        "Where training data is personal data, record this "
                        "assessment against the applicable data-protection "
                        "criteria before deployment.",
                    ],
                },
                based_on=group,
            )
        )
    return findings


def _provisional_thresholds(
    observations: List[Observation], registry: ThresholdRegistry
) -> List[Dict[str, Any]]:
    """
    Record which severity boundaries used here are not yet confirmed.

    Collected over the metrics actually observed, so the disclosure describes
    this run rather than the ontology in general.  Derived metrics are excluded
    for the reason they are not classified in the first place: they restate
    another measurement and no threshold was applied to them.

    Returned as structured data rather than prose so a reader can tell which
    boundary is in question; ``_threshold_caveat`` turns it into the sentence
    that travels in ``scopeLimitations``.
    """
    provisional: List[Dict[str, Any]] = []
    for metric in sorted({observation.metric for observation in observations}):
        definition = registry.get(metric)
        if definition is None or definition.derived_from:
            continue
        for threshold in definition.provisional_thresholds():
            provisional.append(
                {
                    "metric": metric,
                    "thresholdIri": threshold.iri,
                    "thresholdName": threshold.local_name,
                    "thresholdValue": threshold.value,
                    "impliesSeverity": threshold.severity,
                    "reason": threshold.provisional_reason,
                }
            )
    return provisional


def _threshold_caveat(provisional: List[Dict[str, Any]]) -> Optional[str]:
    """
    The provisional-threshold disclosure, phrased for a report reader.

    One sentence covering all provisional boundaries rather than one per
    threshold: the qualification is the same in each case, and repeating it
    three times in ``scopeLimitations`` would bury the limitations that are
    about this particular sweep.

    Says explicitly that the *measurements* are unaffected.  Without that
    distinction the caveat reads as doubt about the tool's figures, which would
    be both wrong and easy to use as grounds for dismissing the finding.
    """
    if not provisional:
        return None
    severities = sorted(
        {str(entry["impliesSeverity"]) for entry in provisional},
        key=lambda label: severity_rank(label),
        reverse=True,
    )
    reasons = [
        str(entry["reason"]) for entry in provisional if entry.get("reason")
    ]
    caveat = (
        "The severity classification in this report rests on threshold values "
        "that are provisional: the boundaries implying "
        f"{', '.join(severities)} have not been confirmed with the team that "
        "owns the attack implementation. The measured advantage figures are the "
        "tool's own and are unaffected; what is unconfirmed is the point at "
        "which a given figure becomes a severity of one level rather than "
        "another, so a verdict close to a boundary may move once the values are "
        "settled."
    )
    if reasons:
        # The longest reason is the most specific one; the others restate the
        # same qualification for adjacent bands.
        caveat += " " + max(reasons, key=len)
    return caveat


def _provisional_metric_semantics(
    observations: List[Observation], registry: ThresholdRegistry
) -> List[Dict[str, Any]]:
    """
    Record which observed metrics are not yet settled in how they are *read*.

    Separate from ``_provisional_thresholds`` because the two qualify different
    steps and are confirmed independently.  A threshold flag says the boundary
    between two severity words may move; this says the value being compared
    against that boundary is open to more than one reading, which no amount of
    agreement about boundaries resolves.  The MIA thresholds are confirmed and
    the sign of ``adv`` is not, so collapsing the two would have dropped the
    remaining qualification along with the settled one.

    Derived metrics are included: a restatement inherits the interpretation of
    the metric it restates, and the reason text is the source metric's.
    """
    semantics: List[Dict[str, Any]] = []
    for metric in sorted({observation.metric for observation in observations}):
        definition = registry.get(metric)
        if definition is None:
            continue
        source = definition
        if definition.derived_from:
            source = registry.get(definition.derived_from) or definition
        if not source.semantics_provisional:
            continue
        semantics.append(
            {
                "metric": metric,
                "metricIri": definition.iri,
                "interpretationOf": source.identifier,
                "reason": source.semantics_provisional_reason,
            }
        )
    return semantics


def _semantics_caveat(semantics: List[Dict[str, Any]]) -> Optional[str]:
    """
    The unsettled-interpretation disclosure, phrased for a report reader.

    Carries the ontology's reason text rather than a summary of it: the reason
    states which reading the normalizer applied and which way an error would
    run, and a reader cannot judge how much weight to put on a finding without
    both.  One entry per distinct reason, so a metric and its derived
    restatement do not produce the same sentence twice.
    """
    reasons: List[str] = []
    for entry in semantics:
        reason = entry.get("reason")
        if reason and str(reason) not in reasons:
            reasons.append(str(reason))
    if not reasons:
        return None
    return (
        "How the measured values are to be interpreted is not fully settled "
        "with the party that owns the measurement. " + " ".join(reasons)
    )


def _scope_limitations(
    rows: List[Dict[str, Any]],
    observations: List[Observation],
    provisional_thresholds: Optional[List[Dict[str, Any]]] = None,
    provisional_semantics: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """
    State what the sweep does not establish.

    Five checks, each a boundary a reader could otherwise mistake for
    coverage: degenerate accuracy, replicated grid cells, the fact that only the
    swept dimensions were varied, whether the severity boundaries themselves are
    confirmed, and whether the measured values have a settled interpretation.

    The two qualifications about the classification come first, boundary before
    interpretation.  The remaining entries qualify how far the numbers
    generalise; these qualify the severity word the reader is most likely to act
    on, and they apply even to a sweep with no other limitation.
    """
    limitations: List[str] = []
    caveat = _threshold_caveat(provisional_thresholds or [])
    if caveat:
        limitations.append(caveat)
    semantics_caveat = _semantics_caveat(provisional_semantics or [])
    if semantics_caveat:
        limitations.append(semantics_caveat)
    if not rows:
        return limitations

    # Degenerate accuracy: if train and test accuracy are identical and
    # saturated across every row, the underlying task is not discriminating
    # and membership-inference numbers from it may not transfer.
    accuracy_values = {
        column: {row[column] for row in rows if column in row}
        for column in _ACCURACY_COLUMNS
    }
    if all(values == {1.0} for values in accuracy_values.values() if values):
        limitations.append(
            "Every swept configuration reports training and test accuracy of "
            "1.0. A task both saturated and showing no generalisation gap is "
            "not representative of production behaviour, so these advantage "
            "figures may not transfer to a deployed model."
        )

    # Replicated grid cells: dimensions are not a unique key, and a repeated
    # cell means the grid is smaller than the row count suggests.
    cells = [tuple(sorted(_dimensions(row).items())) for row in rows]
    duplicates = {cell for cell in cells if cells.count(cell) > 1}
    if duplicates:
        described = "; ".join(
            _format_dimensions(dict(cell)) for cell in sorted(duplicates)
        )
        limitations.append(
            f"{len(rows)} rows cover {len(set(cells))} distinct parameter "
            f"combinations; repeated configurations ({described}) are "
            "replicates rather than additional coverage."
        )

    # Swept dimensions only.  Anything outside the grid is untested, which is
    # the statement a compliance reader needs.
    # Sort numerics numerically and text alphabetically, so a batch-size list
    # reads "32, 64, 128" rather than the string order "128, 32, 64".
    def _sort_key(value: Any) -> Tuple[int, float, str]:
        if isinstance(value, (int, float)):
            return (0, float(value), "")
        return (1, 0.0, str(value))

    swept = {
        column: sorted(
            {row[column] for row in rows if column in row}, key=_sort_key
        )
        for column in _DIMENSION_COLUMNS
    }
    swept_description = "; ".join(
        f"{column}: {', '.join(str(value) for value in values)}"
        for column, values in swept.items()
        if values
    )
    if swept_description:
        limitations.append(
            f"Only these parameter values were exercised ({swept_description}). "
            "Configurations outside this grid, and attack types other than the "
            "one the MIA service executed, are untested."
        )

    return limitations


def _external_scope_statement(
    rows: List[Dict[str, Any]],
    provisional_thresholds: Optional[List[Dict[str, Any]]] = None,
    provisional_semantics: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    """
    State the same boundaries in wording that may leave the organisation.

    Deliberately not derived from ``_scope_limitations``.  That prose names the
    swept values, so that a colleague can check whether the grid covered their
    configuration; naming them to a customer discloses how the model was trained.
    What survives the translation is the *shape* of the boundary — a bounded
    grid, a single attack type — which is what qualifies the verdict and is all
    an external reader needs in order not to over-read it.

    The provisional-threshold and unsettled-interpretation caveats are included,
    in their own wording.  An external artifact is released only for a clean
    verdict, and a clean verdict is precisely a statement that every measured
    value fell below the boundaries — so if those boundaries are unconfirmed, or
    if what the values mean is unconfirmed, the released claim depends on that
    exactly as an adverse one would.  Withholding a caveat here while stating it
    internally would put the qualification only in front of the readers least
    likely to over-read the verdict.  The internal figures, column names and
    threshold names stay out; what leaves is that the classification criteria, or
    the reading of the measurements, are not yet settled.
    """
    if not rows:
        return []
    statement = [
        "The assessment measured membership-inference vulnerability across a "
        "bounded set of training configurations. Configurations outside that "
        "set were not measured, and this result does not extend to them.",
        "One class of membership-inference attack was executed. Other attack "
        "classes, and privacy properties other than membership inference, were "
        "outside the scope of this assessment.",
    ]
    if provisional_thresholds:
        statement.append(
            "The criteria used to classify a measured value as acceptable are "
            "provisional and pending confirmation by the authors of the "
            "measurement method. This result reflects the criteria in force at "
            "the time of assessment and may be revised when they are settled."
        )
    if provisional_semantics:
        # Deliberately does not name the column, the reading applied, or the
        # direction of the possible error: internally those let a colleague
        # judge the weight of a specific finding, and there is no specific
        # finding in a released statement to judge.  What an external reader
        # needs is that the verdict rests on an interpretation still being
        # confirmed, which is what qualifies it.
        statement.append(
            "One aspect of how the measurements are to be interpreted is still "
            "being confirmed with the authors of the measurement method. The "
            "measured values themselves are unaffected, and the interpretation "
            "applied here is the more conservative of those available."
        )
    accuracy_values = {
        column: {row[column] for row in rows if column in row}
        for column in _ACCURACY_COLUMNS
    }
    if all(values == {1.0} for values in accuracy_values.values() if values):
        statement.append(
            "The models exercised in this assessment fit their evaluation data "
            "exactly, which is not representative of production behaviour. The "
            "result should be read as indicative rather than as a measurement "
            "of a deployed system."
        )
    return statement


def normalize(
    raw_result: Dict[str, Any],
    intent: Optional[Dict[str, Any]] = None,
    registry: Optional[ThresholdRegistry] = None,
) -> FactModel:
    """
    Normalise an MIA membership-inference result into a ``FactModel``.

    Parameters
    ----------
    raw_result : dict
        The result returned by ``run_mia_assessment`` -- an envelope with
        ``status`` and ``data``, where ``data`` is the sweep table.
    intent : dict, optional
        The originating intent.  Its ``assessment.parameters`` (attack type,
        shadow model count) are recorded as method context when present.
    registry : ThresholdRegistry, optional
        Injected in tests; loaded from the ontology otherwise.

    Returns
    -------
    FactModel
        Always returned.  A parsing problem is recorded in
        ``normalization_error`` rather than raised, so a completed assessment
        is never lost to an unreadable table.
    """
    registry = registry or load_registry()

    # Criteria the intent named, and whether this skill can evidence them.
    # Resolved on every path, including the failure paths: an intent that
    # claimed GDPR coverage and got no result needs that stated, not omitted.
    # ``produced_evidence=False`` keeps a failed run from reporting the
    # obligations the skill *could* have covered as though it had.
    def _coverage(produced_evidence: bool) -> Dict[str, Any]:
        return coverage_for_intent(
            intent, SKILL_NAME, produced_evidence=produced_evidence
        )

    raw_status = str(raw_result.get("status", "")).upper()
    if raw_status in {"ERROR", "FAILED", "FAILURE"}:
        return FactModel(
            shape="parameterSweep",
            skill=SKILL_NAME,
            status="FAILED",
            regulatory_coverage=_coverage(False),
            normalization_error=str(
                raw_result.get("message") or raw_result.get("error") or
                "MIA service reported a failure"
            ),
        )

    data = raw_result.get("data")
    if isinstance(data, dict):
        # Defensive: the MIA service returns text for this assessment, but the tool
        # wrapper passes through JSON when the content type says so.
        return FactModel(
            shape="parameterSweep",
            skill=SKILL_NAME,
            status="INCONCLUSIVE",
            method={"rawDataKeys": sorted(data.keys())},
            regulatory_coverage=_coverage(False),
            normalization_error=(
                "MIA service returned a JSON object rather than the expected sweep "
                "table; no sweep parser is defined for this shape"
            ),
        )
    if not isinstance(data, str) or not data.strip():
        return FactModel(
            shape="parameterSweep",
            skill=SKILL_NAME,
            status="INCONCLUSIVE",
            regulatory_coverage=_coverage(False),
            normalization_error="MIA result contained no sweep data",
        )

    rows, problems = parse_sweep_table(data)
    if not rows:
        return FactModel(
            shape="parameterSweep",
            skill=SKILL_NAME,
            status="INCONCLUSIVE",
            regulatory_coverage=_coverage(False),
            normalization_error="; ".join(problems)
            or "no readable rows in MIA sweep table",
        )

    observations = _build_observations(rows, registry)
    summaries = _summarise(observations, registry)
    findings = _derive_findings(observations, registry)
    provisional = _provisional_thresholds(observations, registry)
    semantics = _provisional_metric_semantics(observations, registry)
    limitations = _scope_limitations(rows, observations, provisional, semantics)

    method: Dict[str, Any] = {
        "assessmentShape": "parameterSweep",
        "tool": "MIA service",
        # Read from the envelope rather than imported from the tool wrapper, so
        # that a stored result normalised later reports the version it actually
        # ran under instead of whatever the constant says today.
        "toolVersion": raw_result.get("version"),
        # How the version was established, not just what it is.  The MIA service exposes no
        # version endpoint, so the value is pinned in tools/mia_assessment.py and
        # describes this checkout's configuration rather than the running
        # service; a reader treating a configured value as a reported one would
        # over-trust it.  ``None`` when the envelope carried no version at all,
        # which is the honest answer for a result produced before it was pinned.
        "toolVersionSource": "pinned" if raw_result.get("version") else None,
        "rowCount": len(rows),
        "distinctConfigurations": len(
            {tuple(sorted(_dimensions(row).items())) for row in rows}
        ),
        "sweptDimensions": list(_DIMENSION_COLUMNS),
        "metricColumns": dict(_METRIC_COLUMNS),
        "thresholdSource": "docs/skills/ontology/intrust.ttl",
        # Named even when empty, so that a report from a later run with
        # confirmed thresholds says so positively rather than by omission —
        # an absent key is indistinguishable from an older normalizer that
        # never checked.
        "provisionalThresholds": provisional,
        "thresholdsConfirmed": not provisional,
        # Recorded alongside, not merged: confirmed boundaries and a confirmed
        # reading of the values are separate claims, and a report that stated
        # only one of them as "confirmed" would be read as asserting both.
        "provisionalMetricSemantics": semantics,
        "metricSemanticsConfirmed": not semantics,
    }
    if intent:
        assessment = intent.get("assessment") or {}
        parameters = assessment.get("parameters") or intent.get("parameters") or {}
        for key in ("attack_type", "num_shadow_models", "num_queries",
                    "confidence_threshold"):
            if key in parameters:
                method[key] = parameters[key]
        criteria = intent.get("criteria")
        if criteria:
            method["criteria"] = criteria

    return FactModel(
        shape="parameterSweep",
        skill=SKILL_NAME,
        status="SUCCESS",
        observations=observations,
        findings=findings,
        metric_summaries=summaries,
        scope_limitations=limitations,
        external_scope_statement=_external_scope_statement(
            rows, provisional, semantics
        ),
        method=method,
        regulatory_coverage=_coverage(True),
        normalization_error="; ".join(problems) if problems else None,
    )
