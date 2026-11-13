# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Deterministic normaliser for Trivy security scanner results.

Trivy produces a unified JSON report structure for all three assessment types
(docker image, filesystem, kubernetes), so a single normalizer handles all
three rather than duplicating the schema knowledge.  The skill name is derived
from the ``assessment_type`` field in the tool wrapper's result envelope.

Why the parsing is here and not in a prompt
-------------------------------------------
Report composition used to hand raw tool output to an LLM to extract the
findings from.  A model asked to both parse and interpret produces figures that
cannot be traced back to the tool — on the MIA sweep it reported the central
tendency as the result and missed that the worst case sat in one corner of the
grid.  Trivy invites the same failure from a different direction: it emits four
structurally distinct finding kinds, each with its own field names for the same
concepts, so a reader without the schema in hand can plausibly conflate them.
Extraction is therefore deterministic Python and lives here.

Shape: findingList, not parameterSweep
--------------------------------------
Trivy assigns a severity to every finding, and each finding stands on its own.
Reporting reduces them by *selection* — a severity floor, a top-N — not by the
aggregation a parameter sweep needs, where dropping rows would destroy the
comparison that is the result.  ``observations`` and ``metric_summaries`` stay
empty: a count of findings is not a measurement of anything.

Severity comes from Trivy and is carried through, not recomputed.  The
``spa:Threshold`` individuals in the ontology classify swept metric values,
which is a different operation from relabelling a verdict a tool has reached.

Three skills, one normalizer
----------------------------
``trivy-docker-image``, ``trivy-filesystem`` and ``trivy-kubernetes`` differ in
what they point Trivy at, not in what Trivy returns: the report schema is
identical and only ``ArtifactType`` distinguishes them.  Three copies of this
schema knowledge would drift apart, so the skill name is derived from the
wrapper's ``assessment_type`` instead.

The severity filter bounds every conclusion
-------------------------------------------
The wrapper requests only HIGH and CRITICAL findings, so LOW and MEDIUM are
never collected.  An empty result therefore establishes "nothing found at HIGH
or CRITICAL", not "clean" — and the empty result is exactly the one a reader is
most likely to over-read, since there are no findings present to suggest the
scan was partial.  The filter is consequently the first scope limitation on
every result, is read from what the scan reported rather than assumed, and is
recorded in ``method`` beside it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from orchestrator.criterion_registry import coverage_for_intent
from orchestrator.fact_model import SEVERITY_ORDER, FactModel, Finding
from tools.secret_masking import REDACTION_NOTE, mask_quoted_values

# Trivy skills served by this normalizer, keyed by assessment_type.
SKILL_NAME_BY_ASSESSMENT_TYPE = {
    "docker_image_security": "trivy-docker-image",
    "filesystem_security": "trivy-filesystem",
    "kubernetes_security": "trivy-kubernetes",
}

# The severity levels the wrapper requests, used only when a result does not
# report the filter it actually ran under (older stored results, hand-built
# fixtures).  ``tools/trivy_scan.SEVERITY_FILTER`` is the real source.
_ASSUMED_SEVERITY_FILTER = "HIGH,CRITICAL"


def _normalize_severity(raw_severity: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Map a Trivy severity onto the fact model's vocabulary.

    Trivy emits UNKNOWN, LOW, MEDIUM, HIGH or CRITICAL.  An unrecognised value —
    including UNKNOWN, and including ``NONE``, which is the fact model's "no
    severity" sentinel and not something a reported finding can carry — is
    recorded as LOW.  Downward rather than upward: the worst severity drives the
    management severity floor and the external release gate, so a guess that
    inflates it would suppress findings from one report and block the other on
    evidence that does not support either.

    Returns ``(severity, note)``, where ``note`` describes any substitution.
    """
    severity = str(raw_severity or "").strip().upper()
    if severity in SEVERITY_ORDER and severity != "NONE":
        return severity, None
    return "LOW", (
        f"severity {severity or '(absent)'!r} is not a recognised level; "
        "recorded as LOW"
    )


def _references(raw: Any, limit: int = 5) -> Tuple[List[str], bool]:
    """
    The first ``limit`` reference URLs, and whether any were dropped.

    Trivy attaches up to dozens of references to a single CVE.  Carrying all of
    them would crowd out the finding in any rendition, so the list is capped and
    the truncation is stated rather than left for a reader to notice.
    """
    if not isinstance(raw, list):
        return [], False
    references = [str(item) for item in raw]
    if len(references) > limit:
        return references[:limit], True
    return references, False


def _finding_from_vulnerability(vuln: Dict[str, Any], target: str) -> Finding:
    """
    Convert a Trivy vulnerability finding into a ``Finding``.

    Schema: ``VulnerabilityID``, ``PkgName``, ``InstalledVersion``,
    ``FixedVersion``, ``Status``, ``Severity``, ``Title``, ``Description``,
    ``PrimaryURL``, ``References``, ``CweIDs``, ``CVSS``.
    """
    vuln_id = vuln.get("VulnerabilityID") or "unidentified vulnerability"
    package = vuln.get("PkgName") or "an unnamed package"
    installed = vuln.get("InstalledVersion") or "unknown version"
    fixed = vuln.get("FixedVersion") or ""

    # Trivy reports CVSS per scoring source (nvd, redhat, ghsa...), which
    # disagree.  The highest is taken: it is the assessment a reader is most
    # likely to be held to, and taking a mean of others' judgements would
    # produce a number no source stands behind.
    cvss_score = None
    for source in (vuln.get("CVSS") or {}).values():
        if isinstance(source, dict):
            score = source.get("V3Score")
            if isinstance(score, (int, float)) and (
                cvss_score is None or score > cvss_score
            ):
                cvss_score = score

    title = f"{vuln_id} in {package} {installed}"

    business_impact = (
        "A dependency in this artifact has a publicly known security defect, so "
        "the means of exploiting it are documented and available. Whether it is "
        "reachable in this deployment has not been established here; if it is, "
        "the consequences are those published for the defect, which can extend "
        "to unauthorised access or loss of availability."
    )
    if fixed:
        business_impact += " A corrected version of the dependency is available."
    else:
        business_impact += (
            " No corrected version is available yet, so the exposure cannot be "
            "closed by updating alone."
        )

    references, truncated = _references(vuln.get("References"))

    if fixed:
        one_line = f"Update {package} from {installed} to {fixed}"
        steps = [
            f"Raise {package} to {fixed} (or later) in the dependency manifest.",
            "Rebuild and redeploy the artifact.",
            "Re-run the assessment to confirm the finding is gone.",
        ]
    else:
        one_line = f"No fix published for {package}; mitigate or replace it"
        steps = [
            f"Confirm with the {package} maintainers whether a fix is planned.",
            "Determine whether the affected code path is reachable in this "
            "deployment; if it is not, record that as an accepted risk with the "
            "reasoning, rather than leaving the finding open.",
            "If it is reachable, mitigate at the boundary or replace the "
            "component.",
        ]

    return Finding(
        title=title,
        severity=_normalize_severity(vuln.get("Severity"))[0],
        business_impact=business_impact,
        technical_detail={
            "findingKind": "vulnerability",
            "vulnerabilityId": vuln_id,
            "pkgName": vuln.get("PkgName"),
            "installedVersion": vuln.get("InstalledVersion"),
            "fixedVersion": fixed or None,
            "status": vuln.get("Status") or None,
            "cweIds": vuln.get("CweIDs") or None,
            "cvssScore": cvss_score,
            "primaryUrl": vuln.get("PrimaryURL") or None,
            "target": target,
        },
        evidence={
            "description": vuln.get("Description") or vuln.get("Title") or "",
            "references": references,
            "referencesTruncated": truncated,
        },
        remediation={"oneLine": one_line, "steps": steps},
    )


def _finding_from_secret(secret: Dict[str, Any], target: str) -> Finding:
    """
    Convert a Trivy secret finding into a ``Finding``.

    Schema: ``RuleID``, ``Category``, ``Severity``, ``Title``, ``StartLine``,
    ``EndLine``, ``Code``, ``Match``.

    Trivy masks the value it matched, but only that one: the context lines it
    includes either side of the match are verbatim source.  In the observed
    output the masked ``CLIENT_SECRET`` line arrives beside unmasked
    ``TENANT_ID`` and ``CLIENT_ID`` assignments — a credential Trivy did not
    flag, sitting next to one it did, would pass through untouched.  Every
    quoted literal is therefore masked here rather than trusting the tool's
    own masking to be complete.  See ``tools/secret_masking``.
    """
    rule_id = secret.get("RuleID") or "unknown-secret"
    kind = secret.get("Title") or "Secret"
    start_line = secret.get("StartLine")
    end_line = secret.get("EndLine")

    location = f"{target}:{start_line}" if start_line else target
    title = f"{kind} in {location}"

    # Rotation, not deletion, is the point: by the time a scanner finds a
    # committed credential it has to be treated as disclosed, and removing the
    # line only hides it from the next scan.
    business_impact = (
        "A credential is present in the scanned source. It must be treated as "
        "already disclosed and revoked at its issuer: anyone who has had access "
        "to the repository, including its history, has had access to the "
        "credential, and removing the line does not withdraw it. Until it is "
        "rotated it remains usable against whatever it protects."
    )

    technical_detail = {
        "findingKind": "secret",
        "ruleId": rule_id,
        "category": secret.get("Category") or None,
        "startLine": start_line,
        "endLine": end_line,
        "target": target,
    }

    code = secret.get("Code") if isinstance(secret.get("Code"), dict) else {}
    lines = [
        {
            "number": line.get("Number"),
            "content": mask_quoted_values(str(line.get("Content") or "")),
            "isCause": bool(line.get("IsCause")),
        }
        for line in (code.get("Lines") or [])
        if isinstance(line, dict)
    ]
    evidence = {
        "codeLines": lines,
        # Trivy masked the matched value; the mask over the surrounding context
        # is ours.  Both are recorded so a reader knows the snippet is not a
        # verbatim copy of the file.
        "maskedByTool": True,
        "maskedDuringNormalisation": True,
        "redacted": True,
        "redactionNote": REDACTION_NOTE,
        "match": mask_quoted_values(str(secret.get("Match") or "")),
    }

    return Finding(
        title=title,
        severity=_normalize_severity(secret.get("Severity"))[0],
        business_impact=business_impact,
        technical_detail=technical_detail,
        evidence=evidence,
        remediation={
            "oneLine": "Revoke and rotate the credential, then purge it from history",
            "steps": [
                f"Revoke the credential at its issuer now — invalidate the key, "
                f"reset the secret, or delete the principal behind {rule_id}.",
                "Issue a replacement and have the deployment read it at runtime "
                "from a secrets manager rather than from the source.",
                "Remove the value from the source file.",
                "Purge it from version-control history (git-filter-repo or BFG) "
                "and check whether it also reached build logs or artifacts.",
                "Record the exposure where credential incidents are tracked; the "
                "window between commit and rotation may need review.",
            ],
        },
    )


def _finding_from_misconfiguration(misconf: Dict[str, Any], target: str) -> Finding:
    """
    Convert a Trivy misconfiguration finding into a ``Finding``.

    Schema: ``Type``, ``ID``, ``Title``, ``Description``, ``Message``,
    ``Namespace``, ``Query``, ``Resolution``, ``Severity``, ``PrimaryURL``,
    ``References``, ``Status``, ``CauseMetadata``.
    """
    misconf_id = misconf.get("ID") or "unidentified check"
    check_title = misconf.get("Title") or "Configuration check failed"
    resolution = misconf.get("Resolution") or ""
    cause = (
        misconf.get("CauseMetadata")
        if isinstance(misconf.get("CauseMetadata"), dict)
        else {}
    )

    title = f"{check_title} ({misconf_id}) in {target}"

    # Trivy's ``Description`` explains the risk in prose already and is written
    # for a reader who is not holding the config file, so it carries the
    # consequence better than a generic sentence would.  It is quoted rather than
    # paraphrased so the report does not overstate what the check establishes.
    description = str(misconf.get("Description") or "").strip()
    business_impact = description or (
        "The configuration does not satisfy a security control this check "
        "enforces, so a safeguard the deployment is assumed to have is absent."
    )
    business_impact += (
        " The check reports the configuration as written; whether the gap is "
        "reachable depends on how the artifact is deployed."
    )

    technical_detail = {
        "findingKind": "misconfiguration",
        "id": misconf_id,
        "type": misconf.get("Type") or None,
        "namespace": misconf.get("Namespace") or None,
        "query": misconf.get("Query") or None,
        "status": misconf.get("Status") or None,
        "provider": cause.get("Provider"),
        "service": cause.get("Service"),
        "primaryUrl": misconf.get("PrimaryURL") or None,
        "target": target,
    }
    if cause.get("StartLine") is not None:
        technical_detail["startLine"] = cause.get("StartLine")
    if cause.get("EndLine") is not None:
        technical_detail["endLine"] = cause.get("EndLine")

    references, truncated = _references(misconf.get("References"))

    steps = [resolution] if resolution else [
        f"Consult the policy behind {misconf_id} to establish what the check "
        "requires."
    ]
    steps += [
        "Apply the change to the configuration under version control, not only "
        "to the running deployment.",
        "Re-run the assessment to confirm the check passes.",
    ]

    return Finding(
        title=title,
        severity=_normalize_severity(misconf.get("Severity"))[0],
        business_impact=business_impact,
        technical_detail=technical_detail,
        evidence={
            # ``Message`` is the actionable instance ("specify at least 1 USER
            # command"); ``Description`` is the general rule, already used above.
            "message": misconf.get("Message") or description,
            "references": references,
            "referencesTruncated": truncated,
        },
        remediation={
            "oneLine": resolution or f"Correct the configuration flagged by {misconf_id}",
            "steps": steps,
        },
    )


def _finding_from_license(lic: Dict[str, Any], target: str) -> Finding:
    """
    Convert a Trivy licence finding into a ``Finding``.

    Schema: ``Severity``, ``Category``, ``PkgName``, ``FilePath``, ``Name``,
    ``Confidence``, ``Link``.
    """
    name = lic.get("Name") or "an unidentified licence"
    package = lic.get("PkgName") or ""
    # Trivy's category ("restricted", "reciprocal", "notice"...) is its own
    # classification and is reported as such: calling every licence finding
    # "restricted" would assert a legal conclusion the scanner did not reach.
    category = str(lic.get("Category") or "").strip()

    title = f"{name} licence"
    if category:
        title += f" ({category})"
    title += f" in {package}" if package else f" in {target}"

    business_impact = (
        f"A dependency is distributed under the {name} licence, which may carry "
        "obligations on redistribution, attribution, or disclosure of source. "
        "Whether those obligations conflict with how this product is shipped is "
        "a legal question, not a security one, and is not decided here."
    )

    return Finding(
        title=title,
        severity=_normalize_severity(lic.get("Severity"))[0],
        business_impact=business_impact,
        technical_detail={
            "findingKind": "license",
            "name": lic.get("Name"),
            "category": category or None,
            "pkgName": package or None,
            "filePath": lic.get("FilePath") or None,
            "confidence": lic.get("Confidence"),
            "link": lic.get("Link") or None,
            "target": target,
        },
        evidence={
            "licenseName": lic.get("Name"),
            "category": category or None,
            "link": lic.get("Link") or None,
            # Trivy infers the licence from file contents and reports how sure it
            # is.  A low confidence means the licence may be misidentified, which
            # matters before anyone acts on the obligation.
            "detectionConfidence": lic.get("Confidence"),
        },
        remediation={
            "oneLine": f"Confirm the {name} obligations are compatible with how this is distributed",
            "steps": [
                f"Verify that {name} is in fact the licence of "
                f"{package or 'the component'}; the scanner infers it from file "
                "contents.",
                "Review the obligations against this product's distribution "
                "model with whoever owns licence compliance.",
                "If they are incompatible, replace the component or obtain an "
                "exception; record the decision either way.",
            ],
        },
    )


# Trivy's four finding arrays, each with the converter for its schema.  The
# arrays share a report but not a shape: the same concept (severity, location,
# identity) is spelled differently in each, which is why there is a converter per
# kind rather than one with branches.
_FINDING_KINDS = (
    ("Vulnerabilities", "vulnerability", _finding_from_vulnerability),
    ("Secrets", "secret", _finding_from_secret),
    ("Misconfigurations", "misconfiguration", _finding_from_misconfiguration),
    ("Licenses", "license", _finding_from_license),
)


def _extract_findings(
    raw_report: Dict[str, Any]
) -> Tuple[List[Finding], List[str]]:
    """
    Flatten Trivy's per-target ``Results`` into canonical findings.

    Returns ``(findings, problems)``.  An entry that cannot be converted is
    skipped and described in ``problems``; the rest are still normalised, since
    losing a whole scan to one unreadable entry would be the worse outcome.
    """
    findings: List[Finding] = []
    problems: List[str] = []

    for index, result in enumerate(raw_report.get("Results") or []):
        if not isinstance(result, dict):
            problems.append(
                f"Results[{index}] is {type(result).__name__}, not an object; skipped"
            )
            continue
        target = str(result.get("Target") or "<unnamed target>")

        for key, kind, convert in _FINDING_KINDS:
            entries = result.get(key)
            if not isinstance(entries, list):
                # Absent or null is normal: a target yields only the kinds its
                # scanner class produces.
                if entries is not None:
                    problems.append(f"{key} for {target} is not a list; skipped")
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    problems.append(f"{kind} entry in {target} is not an object; skipped")
                    continue
                try:
                    findings.append(convert(entry, target))
                except Exception as error:  # noqa: BLE001 - one bad entry only
                    problems.append(f"unreadable {kind} in {target}: {error}")
                else:
                    _, note = _normalize_severity(entry.get("Severity"))
                    if note:
                        problems.append(f"{kind} in {target}: {note}")

    return findings, problems


def _scanner_classes(raw_report: Dict[str, Any]) -> List[str]:
    """The distinct ``Class`` values across the report's targets, sorted."""
    return sorted(
        {
            str(result.get("Class"))
            for result in raw_report.get("Results") or []
            if isinstance(result, dict) and result.get("Class")
        }
    )


def _build_scope_limitations(
    raw_result: Dict[str, Any],
    raw_report: Dict[str, Any],
    severity_filter: str,
) -> List[str]:
    """
    State the boundaries of what this scan establishes.

    The severity filter comes first and is emitted unconditionally, because it is
    the boundary most likely to be misread: the wrapper requests only HIGH and
    CRITICAL, so an empty result means "nothing at those two levels was found",
    not "the target is clean".  Without this stated, a zero-finding scan reads as
    an all-clear that the scan never attempted to establish — and that reading is
    what would reach a release decision or a customer.
    """
    limitations: List[str] = []

    requested = [level.strip().upper() for level in severity_filter.split(",") if level.strip()]
    withheld = [level for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
                if level not in requested]
    if withheld:
        limitations.append(
            f"The scan requested only {' and '.join(requested)} severity findings, "
            f"so {', '.join(withheld)} findings were never collected. An empty or "
            "short result therefore establishes only that nothing was found at "
            f"{' or '.join(requested)} — it is not evidence that the target has no "
            "issues at the levels that were not requested."
        )

    artifact = raw_report.get("ArtifactName") or raw_result.get("target") or "the target"
    artifact_type = raw_report.get("ArtifactType") or raw_result.get("assessment_type")
    described = f"'{artifact}'" + (f" ({artifact_type})" if artifact_type else "")
    limitations.append(
        f"Only {described} was scanned. Dependencies resolved at runtime, "
        "configuration applied outside the artifact, and anything the scanner "
        "could not open were not examined."
    )

    classes = _scanner_classes(raw_report)
    target_count = len(raw_report.get("Results") or [])
    if classes:
        limitations.append(
            f"{target_count} scan target(s) produced results, covering: "
            f"{', '.join(classes)}. A category absent from that list produced no "
            "results, which may mean the scanner for it did not run rather than "
            "that it found nothing."
        )
    else:
        limitations.append(
            f"{target_count} scan target(s) produced results, but none recorded "
            "which scanner category it came from, so which checks ran cannot be "
            "confirmed from this result."
        )

    # The wrapper reports the scanners it enabled.  Licence detection is not
    # among them for a filesystem scan, so no licence finding can appear —
    # a distinction that matters because "no licence findings" would otherwise
    # look like a licence review.
    scanners = str(raw_result.get("scanners") or "")
    if scanners and "license" not in scanners:
        limitations.append(
            f"The scanners enabled were: {scanners}. Licence detection was not "
            "among them, so this result says nothing about the licences of the "
            "components present."
        )

    metadata = raw_report.get("Metadata") if isinstance(raw_report.get("Metadata"), dict) else {}
    currency = ""
    updated_at = metadata.get("UpdatedAt") or (
        (raw_report.get("Trivy") or {}).get("VulnerabilityDBUpdatedAt")
        if isinstance(raw_report.get("Trivy"), dict)
        else None
    )
    if updated_at:
        currency = f" The vulnerability database used was last updated {updated_at}."
    limitations.append(
        "Trivy reports issues that are already known to its vulnerability and "
        "policy databases. A defect that is unpublished, specific to this "
        "codebase's logic, or newer than the database will not appear, so the "
        "absence of a finding is not evidence that no defect exists." + currency
    )

    return limitations


def _build_external_scope_statement(
    raw_result: Dict[str, Any],
    severity_filter: str,
) -> List[str]:
    """
    State the same boundaries in wording that may leave the organisation.

    Not derived from ``_build_scope_limitations``: that prose names the artifact,
    the target count and the database timestamp so a colleague can reconcile them,
    and an artifact name is often an internal image or repository path.  The
    severity filter, by contrast, translates directly and is the one boundary
    that must survive — it is the difference between "nothing was found" and
    "nothing was found at the two levels that were looked for".
    """
    requested = [
        level.strip().upper()
        for level in severity_filter.split(",")
        if level.strip()
    ]
    withheld = [
        level
        for level in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")
        if level not in requested
    ]

    statement: List[str] = []
    if requested and withheld:
        statement.append(
            f"The assessment collected findings at {' and '.join(requested)} "
            "severity only. Findings at lower severity levels were not collected, "
            "and this result makes no statement about them."
        )
    elif requested:
        statement.append(
            "The assessment collected findings at all severity levels the "
            "scanner reports."
        )

    statement.append(
        "A single artifact was scanned as supplied. Dependencies resolved at "
        "runtime, configuration applied outside that artifact, and anything the "
        "scanner could not open were not examined."
    )
    statement.append(
        "The scanner reports issues already published in its vulnerability and "
        "policy databases. A defect that is unpublished, specific to this "
        "codebase's own logic, or newer than the database will not appear, so no "
        "finding is not the same as no defect."
    )

    scanners = str(raw_result.get("scanners") or "")
    if scanners and "license" not in scanners:
        statement.append(
            "Licence detection was not among the checks performed, so this "
            "result says nothing about the licences of the components present."
        )
    return statement


def normalize(
    raw_result: Dict[str, Any],
    intent: Optional[Dict[str, Any]] = None,
) -> FactModel:
    """
    Normalise a Trivy scan result into a FactModel.

    Parameters
    ----------
    raw_result : dict
        The result returned by one of the Trivy scan functions
        (scan_docker_image, scan_fs, scan_k8_cluster).  Must contain:
        - ``status``: SUCCESS | FAILED | ERROR
        - ``assessment_type``: docker_image_security | filesystem_security |
          kubernetes_security
        - ``tool``: "Trivy"
        - ``version``: tool version
        - ``target``: scanned artifact path/name
        - ``raw``: the full Trivy JSON report (optional; if absent, only counts
          are available)
    intent : dict, optional
        The originating intent.  Its ``criteria`` are resolved against the
        ontology and recorded in ``regulatory_coverage``.

    Returns
    -------
    FactModel
        Always returned.  A parsing problem is recorded in
        ``normalization_error`` rather than raised, so a completed assessment
        is never lost to an unreadable report.
    """
    if not isinstance(raw_result, dict):
        return FactModel(
            shape="findingList",
            skill="trivy",
            status="INCONCLUSIVE",
            regulatory_coverage=coverage_for_intent(
                intent, None, produced_evidence=False
            ),
            normalization_error=(
                f"expected a Trivy result object, received {type(raw_result).__name__}"
            ),
        )

    # Which of the three Trivy skills ran is read from the assessment type the
    # wrapper recorded.  An unrecognised type resolves to no skill rather than a
    # guessed name: the skill name is what criterion coverage is looked up by, and
    # a name that is not in the ontology would silently resolve every criterion to
    # "not assessed" while looking like a successful lookup.
    assessment_type = str(raw_result.get("assessment_type") or "")
    skill = SKILL_NAME_BY_ASSESSMENT_TYPE.get(assessment_type)
    unknown_type_note: Optional[str] = None
    if skill is None:
        unknown_type_note = (
            f"assessment type {assessment_type or '(absent)'!r} is not one of "
            f"{', '.join(sorted(SKILL_NAME_BY_ASSESSMENT_TYPE))}; the Trivy skill "
            "that produced this result could not be identified, so no criterion "
            "coverage was resolved"
        )

    def _coverage(produced_evidence: bool) -> Dict[str, Any]:
        return coverage_for_intent(
            intent, skill, produced_evidence=produced_evidence and skill is not None
        )

    raw_status = str(raw_result.get("status", "")).upper()
    skill_label = skill or "trivy"
    if raw_status in {"ERROR", "FAILED", "FAILURE"}:
        return FactModel(
            shape="findingList",
            skill=skill_label,
            status="FAILED",
            regulatory_coverage=_coverage(False),
            normalization_error=str(
                raw_result.get("message")
                or raw_result.get("error")
                or "Trivy reported a failure"
            ),
        )

    raw_report = raw_result.get("raw")
    if not isinstance(raw_report, dict):
        return FactModel(
            shape="findingList",
            skill=skill_label,
            status="INCONCLUSIVE",
            method={
                "assessmentShape": "findingList",
                "tool": "Trivy",
                "assessmentType": assessment_type,
                "toolMetrics": raw_result.get("metrics") or {},
            },
            regulatory_coverage=_coverage(False),
            normalization_error=(
                "the tool wrapper did not retain Trivy's report, so only "
                "aggregate counts are available and no individual finding can "
                "be reported"
            ),
        )

    # The filter the scan actually ran under, when the wrapper recorded it.  An
    # older stored result predates that field, so the wrapper's current setting
    # is assumed and the assumption is stated rather than presented as fact.
    severity_filter = str(raw_result.get("severityFilter") or "")
    filter_note: Optional[str] = None
    if not severity_filter:
        severity_filter = _ASSUMED_SEVERITY_FILTER
        filter_note = (
            f"the result did not record its severity filter; scope limitations "
            f"assume the configured {_ASSUMED_SEVERITY_FILTER}"
        )

    findings, problems = _extract_findings(raw_report)
    if filter_note:
        problems.append(filter_note)
    if unknown_type_note:
        problems.append(unknown_type_note)

    # Counts derived from the findings actually built, so they reconcile against
    # the wrapper's own ``metrics`` and a discrepancy is visible.
    severity_counts: Dict[str, int] = {}
    kind_counts: Dict[str, int] = {}
    for finding in findings:
        severity_counts[finding.severity] = severity_counts.get(finding.severity, 0) + 1
        kind = str(finding.technical_detail.get("findingKind") or "unknown")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    trivy_meta = raw_report.get("Trivy") if isinstance(raw_report.get("Trivy"), dict) else {}
    method: Dict[str, Any] = {
        "assessmentShape": "findingList",
        "tool": "Trivy",
        "toolVersion": raw_result.get("version") or trivy_meta.get("Version"),
        "assessmentType": assessment_type,
        "artifactName": raw_report.get("ArtifactName") or raw_result.get("target"),
        "artifactType": raw_report.get("ArtifactType"),
        "schemaVersion": raw_report.get("SchemaVersion"),
        "findingCount": len(findings),
        "severityCounts": severity_counts,
        "findingKindCounts": kind_counts,
        "scanTargetCount": len(raw_report.get("Results") or []),
        "scannerClasses": _scanner_classes(raw_report),
        # Recorded because it is the reason for the first scope limitation: the
        # filter bounds what the result can establish, so a reader checking the
        # limitation can see the setting it came from.
        "severityFilter": severity_filter,
        "severityFilterAssumed": bool(filter_note),
        "scannersEnabled": raw_result.get("scanners"),
        "toolVerdictField": "assessment",
        "toolVerdict": raw_result.get("assessment"),
        "toolMetrics": raw_result.get("metrics") or {},
    }
    if isinstance(intent, dict):
        criteria = intent.get("criteria")
        if not criteria and isinstance(intent.get("assessment"), dict):
            criteria = intent["assessment"].get("criteria")
        if criteria:
            method["criteria"] = criteria
    if isinstance(trivy_meta.get("VulnerabilityDBUpdatedAt"), str):
        method["vulnerabilityDbUpdatedAt"] = trivy_meta["VulnerabilityDBUpdatedAt"]

    # Zero findings is a real clean-at-this-filter result, not a degradation.  The
    # scope limitations are what stop it reading as an unqualified all-clear.
    return FactModel(
        shape="findingList",
        skill=skill_label,
        status="SUCCESS",
        findings=findings,
        # A findingList carries no swept metric, so there is nothing to observe
        # or aggregate; a finding count is not a measurement.
        observations=[],
        metric_summaries=[],
        scope_limitations=_build_scope_limitations(
            raw_result, raw_report, severity_filter
        ),
        external_scope_statement=_build_external_scope_statement(
            raw_result, severity_filter
        ),
        method=method,
        regulatory_coverage=_coverage(True),
        normalization_error="; ".join(problems) if problems else None,
    )
