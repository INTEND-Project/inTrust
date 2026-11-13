# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Severity classification driven by the ontology's threshold individuals.

A metric observation's severity is not a judgement made while authoring a
report — it is derived by comparing the observed value against the
``spa:Threshold`` individuals declared for that metric in
``docs/skills/ontology/intrust.ttl``.  Each threshold states a value, a
comparison operator, and (via ``spa:impliesSeverity``) the severity it
implies.

Consequences of putting the mapping in the ontology:

- Changing where "high risk" starts is an ontology edit, reviewable in a
  diff, not a prompt change.
- A report can cite the threshold individual that classified each
  observation, so the classification is traceable.
- ``spa:higherIsWorse`` records metric polarity explicitly, which the value
  alone does not reveal: an attack advantage worsens as it rises, while an
  attacker-accuracy score worsens as it falls away from chance level.
- Two kinds of unconfirmed-ness are recorded separately, because they are
  settled by different agreements: ``spa:thresholdProvisional`` says a boundary
  may move, and ``spa:metricSemanticsProvisional`` says the value being
  compared against it is open to more than one reading.  Confirming the
  boundaries of a metric does not confirm how its values read, so a normalizer
  that treated them as one flag would drop the second when the first was
  cleared.

Metrics are looked up by ``spa:metricIdentifier``, the stable key a
normalizer uses to bind a raw tool output column to its definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ONTOLOGY_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "skills"
    / "ontology"
    / "intrust.ttl"
)

# Maps the ontology's comparison operator vocabulary onto predicates.
_OPERATORS = {
    "greater-than": lambda v, t: v > t,
    "greater-than-or-equal": lambda v, t: v >= t,
    "less-than": lambda v, t: v < t,
    "less-than-or-equal": lambda v, t: v <= t,
    "equal": lambda v, t: v == t,
    "not-equal": lambda v, t: v != t,
}

# ``spa:SeverityHigh`` -> "HIGH".  The ontology names severities as
# individuals; the fact model uses plain labels.
_SEVERITY_PREFIX = "Severity"


@dataclass(frozen=True)
class Threshold:
    """One severity boundary declared for a metric."""

    iri: str
    local_name: str
    value: float
    operator: str
    severity: str
    comment: Optional[str] = None
    # Whether the value is still awaiting confirmation by whoever owns the
    # metric's semantics.  Read from ``spa:thresholdProvisional`` rather than
    # inferred from the comment prose, because a normalizer has to carry it
    # into every report that depends on this boundary: the threshold is the
    # step that turns a measured number into a severity word, and a reader
    # acting on that word cannot see the ontology.
    provisional: bool = False
    provisional_reason: Optional[str] = None

    def matches(self, observed: float) -> bool:
        predicate = _OPERATORS.get(self.operator)
        if predicate is None:
            return False
        return predicate(observed, self.value)


@dataclass(frozen=True)
class MetricDefinition:
    """A metric definition and its severity thresholds, read from the ontology."""

    identifier: str
    iri: str
    label: Optional[str]
    unit: Optional[str]
    definition_text: Optional[str]
    higher_is_worse: bool
    aggregation_function: Optional[str]
    thresholds: Tuple[Threshold, ...]
    derived_from: Optional[str] = None
    derivation_expression: Optional[str] = None
    # Whether how this metric's values are to be read is still unconfirmed by
    # whoever owns the measurement.  Separate from ``Threshold.provisional``:
    # that qualifies where a boundary sits, this qualifies what the value means
    # before any boundary is applied, so it outlives the confirmation of every
    # threshold on the metric.
    semantics_provisional: bool = False
    semantics_provisional_reason: Optional[str] = None

    def classify(self, observed: float) -> Tuple[str, Optional[str]]:
        """
        Return ``(severity, threshold_iri)`` for an observed value.

        Thresholds are tested strongest-first so the most severe matching
        band wins.  ``("NONE", None)`` when no threshold matches.

        The magnitude is compared, not the signed value: for a bidirectional
        metric such as membership-inference advantage, the sign is read as
        recording which way the adversary's bias runs rather than as lessening
        the leak.  That is the conservative choice where the sign's meaning is
        itself unconfirmed — see ``semantics_provisional`` — since it cannot
        classify a leak as smaller than it is.  Only metrics whose thresholds
        are all upper bounds (``greater-than*``) are treated this way; a metric
        with lower-bound thresholds is compared as signed, since there the sign
        is meaningful.
        """
        upper_bounded = all(
            t.operator.startswith("greater-than") for t in self.thresholds
        )
        candidate = abs(observed) if upper_bounded else observed

        ranked = sorted(self.thresholds, key=lambda t: t.value, reverse=True)
        for threshold in ranked:
            if threshold.matches(candidate):
                return threshold.severity, threshold.iri
        return "NONE", None

    def provisional_thresholds(self) -> Tuple[Threshold, ...]:
        """
        The thresholds whose values are not yet confirmed.

        Exposed so a normalizer can disclose the qualification without
        rediscovering which boundaries carry it.  Note that this reports every
        provisional threshold for the metric, not only the one that classified a
        given observation: a "NONE" verdict also rests on the boundaries the
        value fell below, so the qualification applies to a clean result too.
        """
        return tuple(t for t in self.thresholds if t.provisional)


class ThresholdRegistry:
    """
    Metric definitions loaded from the ontology, keyed by metric identifier.

    Built once and reused; the ontology graph is parsed lazily on first use.
    """

    def __init__(self, definitions: Dict[str, MetricDefinition]) -> None:
        self._definitions = definitions

    def get(self, metric_identifier: str) -> Optional[MetricDefinition]:
        return self._definitions.get(metric_identifier)

    def list(self) -> List[MetricDefinition]:
        return list(self._definitions.values())


_registry: Optional[ThresholdRegistry] = None


def _local_name(iri: str) -> str:
    for sep in ("#", "/"):
        if sep in iri:
            return iri.rsplit(sep, 1)[-1]
    return iri


def _severity_label(iri: str) -> str:
    """``.../spa#SeverityHigh`` -> ``"HIGH"``."""
    name = _local_name(iri)
    if name.startswith(_SEVERITY_PREFIX):
        return name[len(_SEVERITY_PREFIX):].upper()
    return name.upper()


def load_registry(
    ontology_path: Optional[Path] = None, force: bool = False
) -> ThresholdRegistry:
    """
    Parse the ontology and build the metric/threshold registry.

    Cached after the first call.  Pass ``force=True`` (or an explicit
    ``ontology_path``) to rebuild, which the tests rely on.
    """
    global _registry
    if _registry is not None and not force and ontology_path is None:
        return _registry

    from rdflib import Graph, Namespace, RDF, RDFS

    path = ontology_path or ONTOLOGY_PATH
    if not path.exists():
        raise FileNotFoundError(f"Ontology file not found at {path}")

    graph = Graph()
    graph.parse(path, format="turtle")
    spa = Namespace("https://intend-project.eu/ontology/spa#")

    def _text(subject, predicate) -> Optional[str]:
        value = graph.value(subject, predicate)
        return str(value) if value is not None else None

    definitions: Dict[str, MetricDefinition] = {}

    for subject in graph.subjects(RDF.type, spa.MetricDefinition):
        identifier = _text(subject, spa.metricIdentifier)
        if not identifier:
            # A definition without a stable key cannot be bound to a raw
            # output column, so normalizers cannot reach it.
            continue

        thresholds: List[Threshold] = []
        for threshold_node in graph.objects(subject, spa.hasThreshold):
            raw_value = graph.value(threshold_node, spa.thresholdValue)
            operator = _text(threshold_node, spa.comparisonOperator)
            severity_node = graph.value(threshold_node, spa.impliesSeverity)
            if raw_value is None or operator is None or severity_node is None:
                # Incomplete threshold: skip rather than guess.  ThresholdShape
                # in the ontology catches these at validation time.
                continue
            provisional_node = graph.value(
                threshold_node, spa.thresholdProvisional
            )
            thresholds.append(
                Threshold(
                    iri=str(threshold_node),
                    local_name=_local_name(str(threshold_node)),
                    value=float(raw_value),
                    operator=operator,
                    severity=_severity_label(str(severity_node)),
                    comment=_text(threshold_node, RDFS.comment),
                    # Absent means confirmed: a threshold is only provisional
                    # if someone says so, so a missing property cannot silently
                    # mark a settled boundary as doubtful.
                    provisional=(
                        bool(provisional_node.toPython())
                        if provisional_node is not None
                        else False
                    ),
                    provisional_reason=_text(
                        threshold_node, spa.thresholdProvisionalReason
                    ),
                )
            )

        higher_is_worse_node = graph.value(subject, spa.higherIsWorse)
        derived_node = graph.value(subject, spa.derivedFromMetric)
        semantics_node = graph.value(subject, spa.metricSemanticsProvisional)

        definitions[identifier] = MetricDefinition(
            identifier=identifier,
            iri=str(subject),
            label=_text(subject, RDFS.label),
            unit=_text(subject, spa.metricUnit),
            definition_text=_text(subject, spa.metricDefinitionText),
            # Absent means "higher is worse", the common case for risk metrics.
            higher_is_worse=(
                bool(higher_is_worse_node.toPython())
                if higher_is_worse_node is not None
                else True
            ),
            aggregation_function=_text(subject, spa.aggregationFunction),
            thresholds=tuple(thresholds),
            derived_from=(
                _text(derived_node, spa.metricIdentifier)
                if derived_node is not None
                else None
            ),
            derivation_expression=_text(subject, spa.derivationExpression),
            # Absent means confirmed, as for a threshold: an interpretation is
            # only open if someone says so.
            semantics_provisional=(
                bool(semantics_node.toPython())
                if semantics_node is not None
                else False
            ),
            semantics_provisional_reason=_text(
                subject, spa.metricSemanticsProvisionalReason
            ),
        )

    registry = ThresholdRegistry(definitions)
    if ontology_path is None:
        _registry = registry
    return registry
