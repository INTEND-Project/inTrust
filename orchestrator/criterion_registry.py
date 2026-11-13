# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Resolves an intent's ``criteria`` list against the ontology, and states what
the assessment did and did not cover.

An intent may declare ``"criteria": ["gdpr", "internal_privacy_policy:v2"]``
(see ``intents/sample_intent_mia.json-orig``).  Until now nothing read that
field.  Naming a criterion is not the same as assessing it, and the gap
between the two is exactly what a compliance reader needs: which obligations
this run produced evidence for, which it did not, and which tokens the
framework does not recognise at all.

Coverage is computed here rather than described by the report-composing LLM,
because "we assessed GDPR" is a claim about the framework's capabilities, not
a phrasing choice.  A criterion counts as *assessed* only when the ontology
declares a requirement under it carrying ``spa:evaluatedBySkill`` naming the
skill that actually ran.

Three outcomes per criterion:

``assessed``
    The skill that ran can evidence at least one requirement under this
    criterion.  Findings bear on it.

``declaredNotAssessed``
    The criterion resolves to a known regulatory source, but no requirement
    under it is evaluable by the skill that ran.  The obligation stands and
    this run says nothing about it.

``unrecognised``
    The token matches no regulatory source in the ontology — for example a
    site-specific policy reference such as ``internal_privacy_policy:v2``.
    Reported as-is rather than silently dropped, since a reader would
    otherwise assume it was handled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ONTOLOGY_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "skills"
    / "ontology"
    / "intrust.ttl"
)


@dataclass(frozen=True)
class Requirement:
    """One obligation derived from a regulatory source."""

    iri: str
    identifier: Optional[str]
    label: Optional[str]
    description: Optional[str]
    source_reference: Optional[str]
    # Skills able to produce evidence bearing on this requirement.  Empty
    # means the framework cannot currently evaluate it.
    evaluated_by_skills: tuple = ()
    privacy_threat_categories: tuple = ()

    def evaluable_by(self, skill: Optional[str]) -> bool:
        return bool(skill) and skill in self.evaluated_by_skills


@dataclass(frozen=True)
class RegulatorySource:
    """A regulation or standard an intent may name in its criteria."""

    iri: str
    criterion_key: str
    identifier: Optional[str]
    label: Optional[str]
    source_reference: Optional[str]
    requirements: tuple = ()


@dataclass(frozen=True)
class CriterionCoverage:
    """The coverage verdict for one criterion named by an intent."""

    criterion: str  # the token as the intent wrote it
    status: str  # assessed | declaredNotAssessed | unrecognised
    source_iri: Optional[str] = None
    source_label: Optional[str] = None
    source_reference: Optional[str] = None
    assessed_requirements: List[Dict[str, Any]] = field(default_factory=list)
    unassessed_requirements: List[Dict[str, Any]] = field(default_factory=list)
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "criterion": self.criterion,
            "status": self.status,
            "sourceIri": self.source_iri,
            "sourceLabel": self.source_label,
            "sourceReference": self.source_reference,
            "assessedRequirements": self.assessed_requirements,
            "unassessedRequirements": self.unassessed_requirements,
            "note": self.note,
        }


class CriterionRegistry:
    """Regulatory sources from the ontology, keyed by criterion token."""

    def __init__(self, sources: Dict[str, RegulatorySource]) -> None:
        self._sources = sources

    def get(self, criterion: str) -> Optional[RegulatorySource]:
        return self._sources.get(_normalise(criterion))

    def list(self) -> List[RegulatorySource]:
        return list(self._sources.values())


def _normalise(token: str) -> str:
    """
    Reduce an intent's criterion token to a lookup key.

    Intents write criteria loosely — ``"gdpr"``, ``"GDPR"``,
    ``"ISO/IEC 27001"``, ``"internal_privacy_policy:v2"``.  A trailing
    ``:version`` suffix is dropped, and separators are stripped, so
    ``"ISO/IEC 27001"`` and ``"iso27001"`` reach the same source.
    """
    text = str(token).strip().lower()
    if ":" in text:
        text = text.split(":", 1)[0]
    for character in (" ", "-", "_", "/", "."):
        text = text.replace(character, "")
    return text


_registry: Optional[CriterionRegistry] = None


def load_registry(
    ontology_path: Optional[Path] = None, force: bool = False
) -> CriterionRegistry:
    """Parse the ontology and index regulatory sources by criterion key."""
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

    # Requirements first, grouped by the source they derive from.
    requirements_by_source: Dict[str, List[Requirement]] = {}
    for subject in graph.subjects(RDF.type, spa.ComplianceRequirement):
        requirement = Requirement(
            iri=str(subject),
            identifier=_text(subject, spa.identifier),
            label=_text(subject, RDFS.label),
            description=_text(subject, spa.description),
            source_reference=_text(subject, spa.sourceReference),
            evaluated_by_skills=tuple(
                sorted(
                    str(value)
                    for value in graph.objects(subject, spa.evaluatedBySkill)
                )
            ),
            privacy_threat_categories=tuple(
                sorted(
                    str(value)
                    for value in graph.objects(
                        subject, spa.addressesPrivacyThreatCategory
                    )
                )
            ),
        )
        for source in graph.objects(subject, spa.derivedFromSource):
            requirements_by_source.setdefault(str(source), []).append(requirement)

    sources: Dict[str, RegulatorySource] = {}
    for subject in graph.subjects(spa.criterionKey, None):
        criterion_key = _text(subject, spa.criterionKey)
        if not criterion_key:
            continue
        source = RegulatorySource(
            iri=str(subject),
            criterion_key=criterion_key,
            identifier=_text(subject, spa.identifier),
            label=_text(subject, RDFS.label),
            source_reference=_text(subject, spa.sourceReference),
            requirements=tuple(requirements_by_source.get(str(subject), ())),
        )
        # Index under the declared key and under the human identifier, so
        # "gdpr" and "GDPR" both resolve.
        sources[_normalise(criterion_key)] = source
        if source.identifier:
            sources.setdefault(_normalise(source.identifier), source)

    registry = CriterionRegistry(sources)
    if ontology_path is None:
        _registry = registry
    return registry


def _requirement_dict(requirement: Requirement) -> Dict[str, Any]:
    return {
        "iri": requirement.iri,
        "identifier": requirement.identifier,
        "label": requirement.label,
        "description": requirement.description,
        "sourceReference": requirement.source_reference,
        "privacyThreatCategories": list(requirement.privacy_threat_categories),
    }


def resolve_coverage(
    criteria: Optional[List[str]],
    skill: Optional[str],
    registry: Optional[CriterionRegistry] = None,
) -> List[CriterionCoverage]:
    """
    Classify each criterion an intent named against what the skill can evidence.

    Parameters
    ----------
    criteria : list of str, optional
        The intent's ``criteria`` list.  ``None`` or empty yields an empty
        result — an intent naming no criteria makes no compliance claim.
    skill : str, optional
        Name of the skill that ran, e.g. ``"mia-privacy"``.
    registry : CriterionRegistry, optional
        Injected in tests; loaded from the ontology otherwise.
    """
    if not criteria:
        return []
    registry = registry or load_registry()

    coverages: List[CriterionCoverage] = []
    for criterion in criteria:
        source = registry.get(criterion)
        if source is None:
            coverages.append(
                CriterionCoverage(
                    criterion=str(criterion),
                    status="unrecognised",
                    note=(
                        "This criterion is not defined in the InTrust ontology, "
                        "so the framework cannot state whether it was met. It "
                        "may be an organisation-specific policy requiring "
                        "manual review."
                    ),
                )
            )
            continue

        assessed = [
            requirement
            for requirement in source.requirements
            if requirement.evaluable_by(skill)
        ]
        unassessed = [
            requirement
            for requirement in source.requirements
            if not requirement.evaluable_by(skill)
        ]

        if assessed:
            status = "assessed"
            note = (
                f"The {skill} assessment produces evidence bearing on "
                f"{len(assessed)} of {len(source.requirements)} requirements "
                f"recorded for this source."
                if len(source.requirements) > len(assessed)
                else None
            )
        else:
            status = "declaredNotAssessed"
            note = (
                "This criterion was named in the intent, but no requirement "
                f"recorded under it can be evaluated by the {skill} "
                "assessment. This report says nothing about whether it is met."
                if skill
                else (
                    "No assessment evidence is attributed to this criterion, "
                    "either because no skill was recorded or because the run "
                    "produced no result."
                )
            )

        coverages.append(
            CriterionCoverage(
                criterion=str(criterion),
                status=status,
                source_iri=source.iri,
                source_label=source.label,
                source_reference=source.source_reference,
                assessed_requirements=[_requirement_dict(r) for r in assessed],
                unassessed_requirements=[
                    _requirement_dict(r) for r in unassessed
                ],
                note=note,
            )
        )
    return coverages


def criteria_from_intent(intent: Optional[Dict[str, Any]]) -> List[str]:
    """
    Pull the criteria list out of an intent, wherever it was written.

    Intents in this repository place it either at the top level or under
    ``assessment`` (compare ``intents/sample_intent_mia.json-orig``), and a
    single criterion is sometimes given as a bare string.
    """
    if not isinstance(intent, dict):
        return []
    for container in (intent, intent.get("assessment") or {}):
        if not isinstance(container, dict):
            continue
        criteria = container.get("criteria")
        if isinstance(criteria, str):
            return [criteria]
        if isinstance(criteria, list) and criteria:
            return [str(criterion) for criterion in criteria]
    return []


def coverage_for_intent(
    intent: Optional[Dict[str, Any]],
    skill: Optional[str],
    registry: Optional[CriterionRegistry] = None,
    produced_evidence: bool = True,
) -> Dict[str, Any]:
    """
    Resolve an intent's criteria into a coverage summary for the fact model.

    Returns an empty dict when the intent names no criteria, so an assessment
    that makes no compliance claim carries no compliance section rather than an
    empty-looking one.  Ontology problems degrade to a recorded error instead of
    failing the assessment: a criteria list is reporting metadata, and losing a
    completed assessment over it would be the worse outcome.

    ``produced_evidence`` must be false when the run failed or was
    inconclusive.  Coverage otherwise reports what the skill is *capable* of
    evidencing, which for a failed run would read as an assessment that
    happened.  Passing ``skill=None`` in that case makes every criterion
    ``declaredNotAssessed``, which is what actually occurred.
    """
    criteria = criteria_from_intent(intent)
    if not criteria:
        return {}
    try:
        coverages = resolve_coverage(
            criteria, skill if produced_evidence else None, registry=registry
        )
    except Exception as error:  # noqa: BLE001 - see docstring
        return {
            "criteriaCount": len(criteria),
            "byStatus": {},
            "complete": False,
            "criteria": [],
            "resolutionError": (
                f"criteria named in the intent could not be resolved against "
                f"the ontology: {error}"
            ),
        }
    return coverage_summary(coverages)


def coverage_summary(coverages: List[CriterionCoverage]) -> Dict[str, Any]:
    """
    Aggregate coverage for the report envelope.

    ``complete`` is true only when every named criterion was assessed.  It is
    deliberately conservative: an unrecognised token counts against
    completeness, because a reader cannot tell from the report alone whether
    it mattered.
    """
    counts: Dict[str, int] = {}
    for coverage in coverages:
        counts[coverage.status] = counts.get(coverage.status, 0) + 1
    return {
        "criteriaCount": len(coverages),
        "byStatus": counts,
        "complete": bool(coverages)
        and counts.get("assessed", 0) == len(coverages),
        "criteria": [coverage.to_dict() for coverage in coverages],
    }
