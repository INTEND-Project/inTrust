# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Audience profiles and deterministic projection of a canonical fact model.

One assessment produces one ``FactModel`` (see ``orchestrator/fact_model.py``).
Different readers need different views of it, but they must not be given
different *results*.  So every rendition here is a pure function of the same
canonical object: field selection, severity filtering, and aggregation.  No
model is called, nothing is recomputed, and two profiles cannot disagree about
what was measured because they read the same instance.

Two axes, deliberately separate
-------------------------------
``audience``
    Who is reading, and therefore which sections and which register.  This is
    a presentation preference and may be taken from the intent's
    ``actor.role`` — which is self-asserted and unverified.

``disclosureClass``
    What may leave the system.  Server-enforced, never read from a request
    body.  Effective content is the intersection of the two, so a request
    claiming ``"role": "SecurityAuditor"`` can change phrasing and layout but
    cannot widen disclosure.

Keeping these apart matters because the audiences are not a single scale.  A
compliance officer needs *more* provenance and method detail than a developer
and *less* code-level detail; an executive needs the aggregate and the
decision, not the matrix.  A scalar "detail level" cannot order them, so each
profile selects sections independently.

Sales is not a fourth detail level
----------------------------------
The three internal profiles *strip* from a superset: miss a field and you
leak.  An external artifact must *allowlist*: miss a field and you merely
omit.  It is also gated twice — on the verdict, so an assessment that found a
high-severity issue produces no artifact at all rather than a softened one; and
on scope, because "no findings" describes a search rather than a target, and a
clean verdict released without the bounds of that search will be read as a
broader claim than the assessment made.  See ``EXTERNAL_ALLOWLIST`` and
``project_external``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from orchestrator.fact_model import SEVERITY_ORDER, severity_rank

# --------------------------------------------------------------------------
# Numeric disclosure
# --------------------------------------------------------------------------
# Reduction of a number is a deterministic function of the canonical value, so
# a banded rendition can never contradict the exact one.  Only granularity
# moves; the underlying value is unchanged.

_BANDS: Tuple[Tuple[int, str], ...] = (
    (0, "none"),
    (3, "a few"),
    (10, "several"),
)


def band_count(count: int) -> str:
    """Reduce a count to a verbal band. Pure and total."""
    for ceiling, label in _BANDS:
        if count <= ceiling:
            return label
    return "many"


def band_magnitude(value: float, threshold: Optional[float]) -> str:
    """
    Describe a measurement relative to its threshold, without the figure.

    Used where a profile suppresses exact values but the reader still needs to
    know whether a limit was crossed and by roughly how much.
    """
    if threshold is None or threshold == 0 or not math.isfinite(threshold):
        return "not comparable to a threshold"
    ratio = abs(value) / abs(threshold)
    if ratio < 0.5:
        return "well within the threshold"
    if ratio < 1.0:
        return "approaching the threshold"
    if ratio < 1.5:
        return "at or just above the threshold"
    return "substantially above the threshold"


# --------------------------------------------------------------------------
# Profiles
# --------------------------------------------------------------------------

# Sections a profile may request.  A profile lists the sections it wants; the
# projector emits only those, in this canonical order, so two profiles sharing
# a section render it identically.
SECTIONS = (
    "verdict",
    "summaryFacts",
    "findings",
    "observations",
    "metricSummaries",
    "method",
    "regulatoryMapping",
    "scopeLimitations",
    "provenance",
    "rawResult",
)


@dataclass(frozen=True)
class ReportProfile:
    """
    One audience's view of an assessment.

    ``sweep_projection`` and ``finding_projection`` name the reduction applied
    to each result shape.  They differ because the shapes reduce differently:
    dropping rows from a parameter sweep destroys the cross-configuration
    comparison that *is* the result, so a sweep is aggregated rather than
    filtered.
    """

    name: str
    # ``spa:Role`` local names, and other role strings an intent might assert.
    roles: Tuple[str, ...]
    sections: Tuple[str, ...]
    register: str
    # exact | banded | verdictOnly
    numeric_disclosure: str = "exact"
    # Findings below this severity are omitted (and the omission is reported).
    # ``None`` for a profile that carries no findings at all.
    severity_floor: Optional[str] = "LOW"
    max_findings: Optional[int] = None
    # Per-finding detail tiers to include.
    include_technical_detail: bool = False
    include_evidence: bool = False
    include_remediation_steps: bool = False
    # argmax | perDimension | full, or ``None`` for a profile that carries no
    # observations at all.
    sweep_projection: Optional[str] = "full"
    # internal | confidential | external
    disclosure_class: str = "confidential"
    description: str = ""


# The four audiences.  Note that these are not ordered by detail: compliance
# takes ``method`` and ``regulatoryMapping`` that the developer profile omits,
# while the developer takes ``observations`` and evidence that compliance does
# not need.
PROFILES: Tuple[ReportProfile, ...] = (
    ReportProfile(
        name="technical",
        roles=(
            "SecurityAuditor", "SecurityAssessor", "Developer", "DevOpsEngineer",
            "MLOpsEngineer", "PrivacyAssessor", "ControlOwner",
        ),
        sections=(
            "verdict", "summaryFacts", "findings", "observations",
            "metricSummaries", "method", "scopeLimitations", "provenance",
        ),
        register="engineer",
        numeric_disclosure="exact",
        severity_floor="LOW",
        include_technical_detail=True,
        include_evidence=True,
        include_remediation_steps=True,
        sweep_projection="full",
        disclosure_class="internal",
        description=(
            "Full measurement detail for the reader who will act on it: every "
            "observation, per-finding technical detail, evidence, and "
            "remediation steps."
        ),
    ),
    ReportProfile(
        name="management",
        roles=("CISO", "Management", "RiskOwner", "SystemOwner", "IntentOwner"),
        sections=(
            "verdict", "summaryFacts", "findings", "metricSummaries",
            "regulatoryMapping", "scopeLimitations",
        ),
        register="executive",
        numeric_disclosure="exact",
        # Deliberately not "HIGH": a MEDIUM finding is a decision input, and
        # the omission count is reported either way.
        severity_floor="MEDIUM",
        max_findings=5,
        include_technical_detail=False,
        include_evidence=False,
        include_remediation_steps=False,
        sweep_projection="argmax",
        disclosure_class="confidential",
        description=(
            "The decision view: verdict, worst case against its threshold, "
            "what it blocks, and the compliance headline. Exact aggregates, no "
            "per-configuration matrix."
        ),
    ),
    ReportProfile(
        name="compliance",
        roles=("ComplianceOfficer", "DPO", "Auditor"),
        sections=(
            "verdict", "summaryFacts", "findings", "regulatoryMapping",
            "method", "scopeLimitations", "provenance", "metricSummaries",
            # Included because "which configurations were exercised" is the
            # coverage question, and the per-dimension reduction below is the
            # answer to it.
            "observations",
        ),
        register="compliance",
        numeric_disclosure="exact",
        severity_floor="LOW",
        include_technical_detail=False,
        include_evidence=False,
        include_remediation_steps=True,
        # Which configurations were exercised is the coverage question, so a
        # per-dimension breakdown rather than a single worst case.
        sweep_projection="perDimension",
        disclosure_class="confidential",
        description=(
            "The traceability view: which obligations this run evidenced, "
            "which it did not, the method and thresholds used, and every "
            "stated limit on scope."
        ),
    ),
    ReportProfile(
        name="external",
        roles=("Sales", "AccountManager", "Customer"),
        sections=("verdict", "summaryFacts", "regulatoryMapping"),
        register="external",
        numeric_disclosure="verdictOnly",
        # Neither reduction applies: the external statement carries no
        # findings and no observations, only a verdict, and any finding at
        # all withholds it (see ``project_external``).
        severity_floor=None,
        max_findings=0,
        sweep_projection=None,
        disclosure_class="external",
        description=(
            "Allowlisted external statement. Produced only when the "
            "assessment found nothing within its stated scope; "
            "carries no target identifiers, paths, or measurements."
        ),
    ),
)

_DEFAULT_PROFILE = "technical"

# Fields an external artifact may contain.  An allowlist, not a denylist: a
# field added to the fact model later is excluded until someone adds it here
# deliberately.
#
# ``scopeStatement`` is on the list because the statement makes a claim that the
# scope qualifies.  A Trivy scan runs at HIGH and CRITICAL only, so a clean
# result means "nothing found at those levels" — released without that bound, a
# customer-facing "no findings" reads as a claim the assessment never made.
#
# ``assessedOn`` and ``validUntil`` are on the list deliberately.  Both are
# dates about the assessment rather than measurements of the target, so neither
# discloses anything the verdict does not; and an expiry the reader cannot see
# is not an expiry.
EXTERNAL_ALLOWLIST = (
    "verdict", "assessmentType", "assessedOn", "validUntil", "statement",
    "criteriaAssessed", "scopeStatement",
)

# An external statement is withheld when the assessment cannot say what it
# examined.  A verdict of "clean" is only meaningful against a stated scope, and
# absent one the reader supplies their own — invariably broader than the scan.
#
# The scope must come from the normalizer's ``externalScopeStatement``.  Reusing
# the internal ``scopeLimitations`` was tried and is wrong: those name paths,
# swept parameter values and model identifiers so that a colleague can check
# them, which is precisely what a released artifact must not carry.
#
# Kept on deliberately, as a reviewed decision rather than a default: the cost is
# more withheld reports, and the reason it is worth paying is that a skill added
# later fails toward silence instead of toward an unqualified "no findings".
_EXTERNAL_REQUIRES_SCOPE = True

# Every condition an assessment must satisfy before an external artifact is
# built.  Reported alongside ``withheldBecause`` so a reader sees the whole set
# of conditions and not only the one that happened to fail: a report withheld
# for an adverse verdict would otherwise read as though a clean verdict were
# sufficient.  Names, not prose — the prose is in ``withheldBecause``.
EXTERNAL_GATES = (
    "verdictMustBeClean",
    "scopeMustBeStatedExternally",
    "normalisationMustBeComplete",
    "assessmentMustBeDated",
    "releaseMustBeApproved",
)

# How long a released statement stands before it has to be re-established.
#
# An external statement describes a component at one moment; the component then
# changes and the artifact does not, so the claim decays silently while
# continuing to read as current.  Ninety days is a judgement, not a derived
# figure: short enough that a statement cannot outlive the code it describes by
# much, long enough to survive an ordinary sales cycle.  Whoever owns the
# release process should set it.
#
# Held as an ISO 8601 duration as well as a day count so the artifact can state
# the rule that produced its expiry date and not only the date.
EXTERNAL_VALIDITY_DAYS = 90
EXTERNAL_VALIDITY_PERIOD = "P90D"


def _shift_days(timestamp: str, days: int) -> Optional[str]:
    """
    Add whole days to an ISO 8601 timestamp, without reading the clock.

    The projector must stay a pure function of its arguments: a rendition is
    re-projected from stored facts on every read, and a wall-clock read here
    would make two reads of one assessment differ.  So the assessment date is
    injected by the caller and the expiry is computed from it.
    """
    from datetime import datetime, timedelta

    text = str(timestamp).strip()
    if not text:
        return None
    # ``fromisoformat`` rejects the trailing "Z" before Python 3.11.
    normalised = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        return None
    return (parsed + timedelta(days=days)).isoformat()


class ProfileRegistry:
    """Profiles indexed by name and by the roles they serve."""

    def __init__(self, profiles: Tuple[ReportProfile, ...]) -> None:
        self._by_name = {profile.name: profile for profile in profiles}
        self._by_role: Dict[str, ReportProfile] = {}
        for profile in profiles:
            for role in profile.roles:
                self._by_role[role.strip().lower()] = profile

    def get(self, name: str) -> Optional[ReportProfile]:
        return self._by_name.get(str(name).strip().lower())

    def for_role(self, role: str) -> Optional[ReportProfile]:
        return self._by_role.get(str(role).strip().lower())

    def default(self) -> ReportProfile:
        return self._by_name[_DEFAULT_PROFILE]

    def names(self) -> List[str]:
        return list(self._by_name)


REGISTRY = ProfileRegistry(PROFILES)


# --------------------------------------------------------------------------
# Profile resolution
# --------------------------------------------------------------------------

def _dig(mapping: Any, *path: str) -> Any:
    current = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def resolve_profile(
    intent: Any,
    requested: Optional[str] = None,
    registry: ProfileRegistry = REGISTRY,
) -> Tuple[ReportProfile, str]:
    """
    Choose a profile, and record why.

    The returned rule string is carried into the rendition.  It is not
    decoration: when a reader asks why their report lost the observation
    matrix, this field is the answer.

    Precedence: an explicit request, then the intent's declared reporting
    preference, then the asserting actor's role, then the default.
    """
    if requested:
        profile = registry.get(requested)
        if profile is not None:
            return profile, f"requested profile={requested}"

    declared = _dig(intent, "reporting", "profile") or _dig(
        intent, "reporting", "detailLevel"
    )
    if declared:
        profile = registry.get(declared)
        if profile is not None:
            return profile, f"intent.reporting.profile={declared}"

    for path in (("actor", "role"), ("requestedBy", "role")):
        role = _dig(intent, *path)
        if role:
            profile = registry.for_role(role)
            if profile is not None:
                return profile, f"{'.'.join(path)}={role}"

    return registry.default(), "default"


def effective_disclosure(
    profile: ReportProfile, permitted: Optional[str] = None
) -> str:
    """
    Narrow a profile's disclosure class to what the caller is permitted.

    ``permitted`` comes from the authenticated caller, never from a request
    body.  The result is the more restrictive of the two, so an intent cannot
    widen disclosure by asserting a role.
    """
    order = ("internal", "confidential", "external")
    if permitted is None:
        return profile.disclosure_class
    try:
        return order[
            max(order.index(profile.disclosure_class), order.index(permitted))
        ]
    except ValueError:
        return "external"


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------

def _project_finding(
    finding: Dict[str, Any], profile: ReportProfile
) -> Dict[str, Any]:
    """Select a finding's detail tiers. Field selection only — no rewording."""
    projected: Dict[str, Any] = {
        "title": finding.get("title"),
        "severity": finding.get("severity"),
    }
    if finding.get("businessImpact"):
        projected["businessImpact"] = finding["businessImpact"]
    if profile.include_technical_detail and finding.get("technicalDetail"):
        projected["technicalDetail"] = finding["technicalDetail"]
    if profile.include_evidence and finding.get("evidence"):
        projected["evidence"] = finding["evidence"]

    remediation = finding.get("remediation") or {}
    if remediation:
        if profile.include_remediation_steps:
            projected["remediation"] = remediation
        elif remediation.get("oneLine"):
            projected["remediation"] = {"oneLine": remediation["oneLine"]}

    if profile.include_technical_detail and finding.get("basedOn"):
        projected["basedOn"] = finding["basedOn"]
    return projected


def _project_observations(
    observations: List[Dict[str, Any]], profile: ReportProfile
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Reduce sweep observations by aggregation rather than by dropping rows.

    ``argmax`` keeps the worst observation per metric; ``perDimension`` keeps
    the worst per swept dimension value, which is what shows *where* risk
    concentrates; ``full`` keeps everything.  In every case the reduction is
    reported, so a reader can tell a summary from the whole.
    """
    if not observations:
        return [], {"projection": profile.sweep_projection, "kept": 0, "total": 0}

    total = len(observations)

    if profile.sweep_projection == "full":
        kept = observations
    elif profile.sweep_projection == "argmax":
        by_metric: Dict[str, Dict[str, Any]] = {}
        for observation in observations:
            metric = observation.get("metric")
            current = by_metric.get(metric)
            if current is None or abs(observation.get("value") or 0) > abs(
                current.get("value") or 0
            ):
                by_metric[metric] = observation
        kept = list(by_metric.values())
    elif profile.sweep_projection == "perDimension":
        # Worst observation for each (dimension, value) pair.  One observation
        # may be the worst along several dimensions; it appears once.
        selected: Dict[int, Dict[str, Any]] = {}
        for observation in observations:
            for name, value in (observation.get("dimensions") or {}).items():
                peers = [
                    candidate
                    for candidate in observations
                    if candidate.get("metric") == observation.get("metric")
                    and (candidate.get("dimensions") or {}).get(name) == value
                ]
                worst = max(peers, key=lambda o: abs(o.get("value") or 0))
                selected[id(worst)] = worst
        kept = list(selected.values())
    else:
        # Fail closed: an unrecognised projection must not quietly show the
        # reader the full sweep.
        raise ValueError(
            f"profile {profile.name!r} has no usable sweep projection "
            f"({profile.sweep_projection!r})"
        )

    reduction = {
        "projection": profile.sweep_projection,
        "kept": len(kept),
        "total": total,
        "omitted": total - len(kept),
    }
    return kept, reduction


def _summary_facts(
    facts: Dict[str, Any], profile: ReportProfile
) -> Dict[str, Any]:
    """
    The fact table every rendition quotes.

    Narrative generation reads only this, never the raw result — so prose can
    phrase these figures but cannot compute new ones.
    """
    findings = facts.get("findings") or []
    counts: Dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity") or "NONE").upper()
        counts[severity] = counts.get(severity, 0) + 1

    summary: Dict[str, Any] = {"worstSeverity": facts.get("worstSeverity")}

    if profile.numeric_disclosure == "exact":
        summary["findingCountsBySeverity"] = counts
        # Counts measurements only.  A derived metric is an algebraic
        # restatement of another, so including it would double the apparent
        # amount of evidence — 13 sweep rows would read as 26 observations.
        derived = {
            metric.get("metric")
            for metric in facts.get("metricSummaries") or []
            if metric.get("derivedFrom")
        }
        summary["observationCount"] = sum(
            1
            for observation in facts.get("observations") or []
            if observation.get("metric") not in derived
        )
    elif profile.numeric_disclosure == "banded":
        summary["findingCountsBySeverity"] = {
            severity: band_count(count) for severity, count in counts.items()
        }
    # verdictOnly: neither counts nor observation totals.

    worst_metric = None
    for metric in facts.get("metricSummaries") or []:
        if metric.get("derivedFrom"):
            # An algebraic restatement of another metric is not independent
            # corroboration, so it is never the headline figure.
            continue
        worst_metric = metric
        break

    if worst_metric:
        headline: Dict[str, Any] = {"metric": worst_metric.get("metric")}
        threshold = _threshold_for(facts, worst_metric.get("metric"))
        if profile.numeric_disclosure == "exact":
            headline["worstValue"] = worst_metric.get("worstValue")
            headline["worstConfiguration"] = worst_metric.get("worstDimensions")
            headline["medianValue"] = worst_metric.get("medianValue")
            headline["thresholdValue"] = threshold
            headline["higherIsWorse"] = worst_metric.get("higherIsWorse")
        else:
            headline["comparison"] = band_magnitude(
                worst_metric.get("worstValue") or 0.0, threshold
            )
        summary["headlineMetric"] = headline

    return summary


def _threshold_for(facts: Dict[str, Any], metric: Optional[str]) -> Optional[float]:
    """Recover the threshold a finding on ``metric`` was classified against."""
    for finding in facts.get("findings") or []:
        detail = finding.get("technicalDetail") or {}
        if detail.get("metric") == metric and detail.get("thresholdValue"):
            return detail["thresholdValue"]
    return None


def project(
    facts: Dict[str, Any],
    profile: ReportProfile,
    resolved_by: str = "unspecified",
    regulatory_mapping: Optional[Dict[str, Any]] = None,
    provenance: Optional[Dict[str, Any]] = None,
    raw_result: Optional[Dict[str, Any]] = None,
    assessed_on: Optional[str] = None,
    approval: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Project a canonical fact model into one audience's rendition.

    Deterministic and side-effect free: the same inputs always yield the same
    output, and no figure is recomputed from anything but ``facts``.  This is why
    ``assessed_on`` is a parameter and not a clock read — see
    ``project_external``.

    ``project_external`` handles the ``external`` profile; routing there is
    automatic so a caller cannot reach the allowlisted path by accident, nor
    bypass it.  ``assessed_on`` and ``approval`` are only consulted there; the
    internal profiles are not gated on either, since an internal reader needs
    the result whether or not anyone has cleared it for release.
    """
    if profile.disclosure_class == "external":
        return project_external(
            facts,
            profile,
            resolved_by,
            regulatory_mapping,
            assessed_on=assessed_on,
            approval=approval,
        )

    sections = set(profile.sections)
    rendition: Dict[str, Any] = {}

    if "verdict" in sections:
        rendition["verdict"] = {
            "status": facts.get("status"),
            "worstSeverity": facts.get("worstSeverity"),
        }

    if "summaryFacts" in sections:
        rendition["summaryFacts"] = _summary_facts(facts, profile)

    omitted_findings = 0
    if "findings" in sections:
        floor = severity_rank(profile.severity_floor)
        eligible = [
            finding
            for finding in (facts.get("findings") or [])
            if severity_rank(finding.get("severity")) >= floor
        ]
        eligible.sort(
            key=lambda f: severity_rank(f.get("severity")), reverse=True
        )
        limited = (
            eligible[: profile.max_findings]
            if profile.max_findings is not None
            else eligible
        )
        omitted_findings = len(facts.get("findings") or []) - len(limited)
        rendition["findings"] = [
            _project_finding(finding, profile) for finding in limited
        ]

    if "observations" in sections:
        kept, reduction = _project_observations(
            facts.get("observations") or [], profile
        )
        rendition["observations"] = kept
        rendition["observationReduction"] = reduction

    if "metricSummaries" in sections:
        rendition["metricSummaries"] = facts.get("metricSummaries") or []

    if "method" in sections:
        rendition["method"] = facts.get("method") or {}

    if "regulatoryMapping" in sections and regulatory_mapping is not None:
        rendition["regulatoryMapping"] = regulatory_mapping

    if "scopeLimitations" in sections:
        # Never truncated. A limitation is a statement about what the
        # assessment does not establish; dropping it would make the rendition
        # read as broader coverage than was achieved.
        rendition["scopeLimitations"] = facts.get("scopeLimitations") or []

    if "provenance" in sections and provenance is not None:
        rendition["provenance"] = provenance

    if "rawResult" in sections and raw_result is not None:
        rendition["rawResult"] = raw_result

    rendition["reportProfile"] = {
        "name": profile.name,
        "register": profile.register,
        "resolvedBy": resolved_by,
        "numericDisclosure": profile.numeric_disclosure,
        "disclosureClass": profile.disclosure_class,
        "severityFloor": profile.severity_floor,
        "sweepProjection": profile.sweep_projection,
        "findingsOmitted": omitted_findings,
        "sections": [s for s in SECTIONS if s in sections],
        # A rendition must be reconcilable against the object it came from,
        # even when it suppresses figures.
        "canonicalWorstSeverity": facts.get("worstSeverity"),
        "canonicalFindingCount": len(facts.get("findings") or []),
        "canonicalObservationCount": len(facts.get("observations") or []),
    }
    return rendition


def project_external(
    facts: Dict[str, Any],
    profile: ReportProfile,
    resolved_by: str = "unspecified",
    regulatory_mapping: Optional[Dict[str, Any]] = None,
    assessed_on: Optional[str] = None,
    approval: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build an allowlisted external statement, or withhold it.

    Gated on the verdict: when the assessment found anything at all, at any
    severity, no artifact is produced.  The honest
    external output for a failed assessment is nothing, and this returns
    exactly that rather than a softened version.

    Gated a second time on scope.  "No findings" is not a property of a target
    but of a search, and a released statement that omits what was searched
    invites the reader to assume the broadest reading.  Trivy makes this
    concrete: it is invoked at HIGH and CRITICAL only, so a zero-finding scan
    passes the verdict gate while never having examined two severity levels.

    The wording comes from ``externalScopeStatement`` and not from
    ``scopeLimitations``: the internal phrasing names paths, parameter values and
    model identifiers in order to be checkable, and those must not leave.  A
    normalizer that has not written external wording produces no statement —
    consistent with the allowlist, silence omits rather than leaks.

    Gated a third time on the date, and a fourth on approval.

    ``assessed_on`` is injected rather than read from the clock here, because
    this function must stay a pure function of its arguments: a rendition is
    re-projected from stored facts on every read, and a statement whose expiry
    moved between two reads of the same assessment would be worthless.  The
    caller passes the job's own completion time.  Absent it there is no expiry
    to compute, and an unexpiring statement is worse than none — the component
    keeps changing while the artifact reads as current forever — so the
    statement is withheld rather than released undated.

    ``approval`` carries the human decision: ``{"state": "approved",
    "approvedBy": ..., "recordedAt": ..., "reference": ...}``.  Nothing here
    verifies the approver's identity; that belongs to whatever fronts this.  What
    is enforced is that an unapproved statement is not released, so that
    ``requiresApprovalBeforeRelease`` names a condition that was checked rather
    than an intention.  Default is unapproved, so a caller that knows nothing
    about approval withholds instead of releasing.

    Built by allowlist (``EXTERNAL_ALLOWLIST``), so a field added to the fact
    model later is excluded until someone includes it deliberately.
    """
    worst = str(facts.get("worstSeverity") or "NONE").upper()
    status = str(facts.get("status") or "").upper()
    scope_statement = [
        str(line)
        for line in (facts.get("externalScopeStatement") or [])
        if str(line).strip()
    ]

    withheld_reasons: List[str] = []
    if status != "SUCCESS":
        withheld_reasons.append(
            f"assessment status is {status or 'unknown'}, not SUCCESS"
        )
    if severity_rank(worst) > 0:
        withheld_reasons.append(
            f"assessment found a {worst}-severity result; an external "
            "statement is only produced for a clean assessment"
        )
    if _EXTERNAL_REQUIRES_SCOPE and not scope_statement:
        withheld_reasons.append(
            "the assessment offered no externally phrased scope statement, so "
            "what it examined cannot be qualified; a clean verdict is only "
            "releasable alongside the bounds of the search that produced it"
        )
    if facts.get("normalizationError"):
        withheld_reasons.append(
            "normalisation of the tool output was incomplete, so the result may "
            "not reflect everything the tool reported"
        )

    valid_until = _shift_days(assessed_on, EXTERNAL_VALIDITY_DAYS) if assessed_on else None
    if not valid_until:
        withheld_reasons.append(
            "the assessment carries no usable date, so the statement could not "
            "be given an expiry; an undated claim about a component that keeps "
            "changing would go on reading as current indefinitely"
        )

    approval = approval if isinstance(approval, dict) else {}
    approval_state = str(approval.get("state") or "pending").strip().lower()
    approved_by = str(approval.get("approvedBy") or "").strip()
    if approval_state != "approved" or not approved_by:
        withheld_reasons.append(
            "release has not been approved by a named person, and this profile "
            "requires approval before an assessment result leaves the "
            "organisation"
        )

    if withheld_reasons:
        marker = {
            "name": profile.name,
            "resolvedBy": resolved_by,
            "disclosureClass": "external",
            "gates": list(EXTERNAL_GATES),
            # Stated on the withheld payload too: the requirement is a property
            # of the profile, not of the outcome, and a reader asking why nothing
            # was released should see that approval was among the conditions
            # rather than infer it from its absence.
            "requiresApprovalBeforeRelease": True,
            "approvalState": approval_state,
        }
        # An approval never travels without its approver, here as well as on the
        # released payload.  This case is the one that is easy to miss: approval
        # was given and some *other* gate withheld the statement, so the state
        # says "approved" on an artifact that was not released, and an approval
        # with nobody attached to it cannot be questioned afterwards.
        if approval_state == "approved" and approved_by:
            marker["approvedBy"] = approved_by
        return {
            "released": False,
            "withheldBecause": withheld_reasons,
            "reportProfile": marker,
        }

    criteria_assessed = [
        coverage.get("sourceLabel") or coverage.get("criterion")
        for coverage in (regulatory_mapping or {}).get("criteria", [])
        if coverage.get("status") == "assessed"
    ]

    candidate = {
        "verdict": "pass",
        "assessmentType": facts.get("skill"),
        "assessedOn": assessed_on,
        "validUntil": valid_until,
        "statement": (
            "An independent automated assessment of this component completed "
            "with no findings within its stated scope. The scope of "
            "that assessment is stated below and qualifies this result. This "
            "statement reflects the component as assessed on the date given and "
            "stands until the validity date; after that it must be "
            "re-established by a fresh assessment."
        ),
        "criteriaAssessed": criteria_assessed,
        # Carried verbatim from the normalizer's external wording.  Not
        # truncated: the qualification is the reason the statement can be
        # released at all, so shortening it would defeat the gate that admitted
        # it.  It describes the search in general terms — what class of thing
        # was looked for and what was not — and so discloses nothing about the
        # component that the verdict does not already.
        "scopeStatement": scope_statement,
    }
    # Allowlist enforcement: anything not named is dropped, including any
    # field a future change might add above.
    released = {
        key: value
        for key, value in candidate.items()
        if key in EXTERNAL_ALLOWLIST
    }
    released["released"] = True
    released["reportProfile"] = {
        "name": profile.name,
        "register": profile.register,
        "resolvedBy": resolved_by,
        "disclosureClass": "external",
        "numericDisclosure": profile.numeric_disclosure,
        "allowlist": list(EXTERNAL_ALLOWLIST),
        "gates": list(EXTERNAL_GATES),
        "requiresApprovalBeforeRelease": True,
        # The requirement above and the record that it was met.  Kept together
        # so neither can be read without the other: the flag on its own says
        # only what ought to have happened.
        "approvalState": "approved",
        "approvedBy": approved_by,
        # The period as well as the date, so a reader can see the rule that
        # produced the expiry rather than only its result.
        "validityPeriod": EXTERNAL_VALIDITY_PERIOD,
    }
    for source, target in (
        ("recordedAt", "approvalRecordedAt"),
        ("reference", "approvalReference"),
    ):
        value = str(approval.get(source) or "").strip()
        if value:
            released["reportProfile"][target] = value
    return released


def project_all(
    facts: Dict[str, Any],
    resolved_by: str = "unspecified",
    regulatory_mapping: Optional[Dict[str, Any]] = None,
    provenance: Optional[Dict[str, Any]] = None,
    raw_result: Optional[Dict[str, Any]] = None,
    assessed_on: Optional[str] = None,
    approval: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Project every profile, for tests and for the ``?profile=all`` view."""
    return {
        profile.name: project(
            facts,
            profile,
            resolved_by=resolved_by,
            regulatory_mapping=regulatory_mapping,
            provenance=provenance,
            raw_result=raw_result,
            assessed_on=assessed_on,
            approval=approval,
        )
        for profile in PROFILES
    }
