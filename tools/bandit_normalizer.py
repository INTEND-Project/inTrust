# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Deterministic normaliser for Bandit static code analysis results.

Bandit returns a list of discrete findings, each already carrying a severity
from the tool (HIGH, MEDIUM, LOW, or sometimes UNDEFINED). Unlike parameter
sweeps, which require aggregation to extract the worst case, findingList
results reduce by *selection*: reporting shows top-N findings or applies a
severity floor, because every finding is already independently meaningful.

Why the parsing is here and not in a prompt
-------------------------------------------
Report composition used to hand raw tool output to an LLM together with the
instruction to extract the findings from it.  A model asked to both parse and
interpret produces numbers and locations that cannot be traced back to the tool,
and it has no reliable way to keep sensitive matched material out of the text it
writes.  Extraction is therefore deterministic Python and lives here.

That second point is concrete for Bandit: the hardcoded-credential checks (B105,
B106, B107) report the matched secret in cleartext in both ``issue_text`` and
``code``.  Those fields are masked here before they enter the canonical facts —
see ``tools/secret_masking`` for why masking belongs at normalisation rather
than at projection.

The three detail tiers
-----------------------
``Finding`` separates ``business_impact``, ``technical_detail``, and
``evidence`` so that audience projection is field selection rather than
rewriting.  A management reader sees only ``title`` and ``business_impact``
with a one-line remediation; a technical reader gets the full location, CWE,
confidence, and unredacted code snippet (when they have permission).

Assessment shape: findingList, not parameterSweep
--------------------------------------------------
These findings carry tool-assigned severities and are discrete, so they reduce
by selection (show HIGH and above; show top-5), not aggregation (worst case
across a swept grid).  The ``FactModel`` is populated with ``findings`` and
empty ``observations`` and ``metric_summaries``.  Severity thresholds in the
ontology are for swept metrics, not for re-classifying tool verdicts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from orchestrator.criterion_registry import coverage_for_intent
from orchestrator.fact_model import SEVERITY_ORDER, FactModel, Finding
from tools.secret_masking import REDACTION_NOTE, mask_quoted_values

SKILL_NAME = "bandit-static-code"

# Bandit test families mapped to business impact statements.
# These describe the consequence (what could happen), not the mechanism
# (what the code does).
_BUSINESS_IMPACT = {
    "hardcoded_credential": (
        "An attacker with access to the source code or version control history "
        "could extract the embedded credential and use it to authenticate "
        "against the target system, bypassing access controls."
    ),
    "subprocess_shell": (
        "An attacker able to influence the input to this subprocess call could "
        "execute arbitrary shell commands on the host system, leading to "
        "data exfiltration, privilege escalation, or denial of service."
    ),
    "insecure_request": (
        "An outbound request is made without a fully enforced transport "
        "safeguard: either the server's certificate is not verified, allowing "
        "an attacker in the network path to intercept or modify data in "
        "transit, or no timeout is set, allowing an unresponsive service to "
        "exhaust the caller's resources."
    ),
    "weak_crypto": (
        "The cryptographic primitive in use is known to be weak or broken. "
        "An attacker could decrypt ciphertext, forge signatures, or recover "
        "keys more easily than the security policy assumes."
    ),
    "unsafe_deserialization": (
        "Deserializing untrusted data can allow an attacker to execute "
        "arbitrary code by crafting a malicious payload, leading to full "
        "system compromise."
    ),
    "assert_used": (
        "Assert statements are removed when Python is run with optimization "
        "flags (-O), so security checks implemented as asserts will not be "
        "enforced in production builds."
    ),
    "sql_injection": (
        "An attacker able to control part of the SQL query string could "
        "extract, modify, or delete database records beyond their intended "
        "access, or execute administrative operations."
    ),
    "yaml_load": (
        "The unsafe YAML loader can execute arbitrary Python code embedded in "
        "the YAML document, allowing an attacker supplying YAML input to "
        "achieve remote code execution."
    ),
    "generic": (
        "This pattern has been flagged by Bandit as a potential security issue. "
        "Review the context to determine whether it is exploitable or can be "
        "mitigated by existing controls."
    ),
}

# One-line remediation statements per test family, for management readers.
_REMEDIATION_ONE_LINE = {
    "hardcoded_credential": (
        "Store credentials in a secrets management system and retrieve them "
        "at runtime using environment variables or a vault API."
    ),
    "subprocess_shell": (
        "Use subprocess with shell=False and a list of arguments, or validate "
        "and sanitize all inputs if shell invocation is unavoidable."
    ),
    "insecure_request": (
        "Enable certificate verification and set appropriate timeout values "
        "for all network requests."
    ),
    "weak_crypto": (
        "Replace the weak algorithm with a current, standards-approved "
        "alternative (e.g., AES-256, SHA-256, or a modern KDF)."
    ),
    "unsafe_deserialization": (
        "Use a safe deserialization format such as JSON, or sign and verify "
        "pickled data before unpickling."
    ),
    "assert_used": (
        "Replace assert statements used for security checks with explicit "
        "conditional raises that are not removed by optimization."
    ),
    "sql_injection": (
        "Use parameterized queries or an ORM to construct SQL statements "
        "instead of string formatting."
    ),
    "yaml_load": (
        "Replace yaml.load() with yaml.safe_load() to prevent arbitrary code "
        "execution from untrusted YAML."
    ),
    "generic": (
        "Review the finding details and apply the remediation recommended by "
        "Bandit's documentation link."
    ),
}


# Bandit test id to family.  The id is matched before the test name because
# Bandit's blacklist checks (B4xx) all report ``test_name="blacklist"``, which
# carries no information about what was flagged — B403 (pickle import) and B404
# (subprocess import) are indistinguishable by name alone.
_FAMILY_BY_TEST_ID = {
    "B101": "assert_used",
    "B105": "hardcoded_credential",
    "B106": "hardcoded_credential",
    "B107": "hardcoded_credential",
    "B113": "insecure_request",
    "B301": "unsafe_deserialization",  # pickle.loads
    "B302": "unsafe_deserialization",  # marshal.loads
    "B303": "weak_crypto",
    "B304": "weak_crypto",
    "B305": "weak_crypto",
    "B324": "weak_crypto",
    "B403": "unsafe_deserialization",  # import pickle
    "B404": "subprocess_shell",        # import subprocess
    "B501": "insecure_request",        # request with verify=False
    "B506": "yaml_load",
    "B602": "subprocess_shell",
    "B603": "subprocess_shell",
    "B604": "subprocess_shell",
    "B605": "subprocess_shell",
    "B606": "subprocess_shell",
    "B607": "subprocess_shell",
    "B608": "sql_injection",           # hardcoded_sql_expressions
    "B609": "subprocess_shell",
}

# Substring of a test name to family, consulted only when the id is unknown.
# Ordered most specific first: "hardcoded_sql_expressions" must not be read as
# a credential just because it begins with "hardcoded".
_FAMILY_BY_NAME_FRAGMENT = (
    ("sql", "sql_injection"),
    ("yaml", "yaml_load"),
    ("pickle", "unsafe_deserialization"),
    ("marshal", "unsafe_deserialization"),
    ("password", "hardcoded_credential"),
    ("secret", "hardcoded_credential"),
    ("token", "hardcoded_credential"),
    ("credential", "hardcoded_credential"),
    ("subprocess", "subprocess_shell"),
    ("shell", "subprocess_shell"),
    ("exec", "subprocess_shell"),
    ("request", "insecure_request"),
    ("ssl", "insecure_request"),
    ("md5", "weak_crypto"),
    ("sha1", "weak_crypto"),
    ("crypt", "weak_crypto"),
    ("hash", "weak_crypto"),
    ("assert", "assert_used"),
)


def _classify_test(test_id: str, test_name: str) -> str:
    """
    Map a Bandit test to a known family for business impact lookup.

    The family determines the plain-language consequence and the one-line
    remediation, and it also decides whether the finding's evidence needs
    redacting.  An unrecognised test falls back to ``"generic"``, which is
    honest about the tool having flagged something without inventing a
    consequence for a check this module has not been taught.

    Returns a family key for ``_BUSINESS_IMPACT`` and ``_REMEDIATION_ONE_LINE``.
    """
    by_id = _FAMILY_BY_TEST_ID.get(test_id.strip().upper())
    if by_id:
        return by_id

    test_name_lower = test_name.lower()
    for fragment, family in _FAMILY_BY_NAME_FRAGMENT:
        if fragment in test_name_lower:
            return family

    return "generic"


def _redact(text: str, is_credential_finding: bool) -> str:
    """
    Mask quoted literals in the evidence of a credential-family finding.

    Bandit reports the *value* it matched, not merely its location: for the
    hardcoded-credential tests both ``issue_text`` and ``code`` carry the
    detected secret in cleartext (``"Possible hardcoded password: 'aBn4T~...'"``).
    See ``tools/secret_masking`` for why this happens during normalisation.

    Text is returned unchanged for other families, so a subprocess or SQL
    finding keeps the snippet that makes it actionable.
    """
    if not is_credential_finding:
        return text
    return mask_quoted_values(text)


# Readable labels for the families, used when Bandit's own test name is not
# informative.  The blacklist checks all report ``test_name="blacklist"``.
_FAMILY_LABEL = {
    "hardcoded_credential": "Hardcoded credential",
    "subprocess_shell": "Subprocess or shell invocation",
    "insecure_request": "Insecure outbound request",
    "weak_crypto": "Weak cryptographic primitive",
    "unsafe_deserialization": "Unsafe deserialization",
    "assert_used": "Assert used for a check",
    "sql_injection": "SQL built by string construction",
    "yaml_load": "Unsafe YAML load",
    "generic": "Potential security issue",
}


def _readable_test_name(test_name: str, family: str) -> str:
    """
    Convert a Bandit test_name into a human-readable label.

    ``"hardcoded_password_string"`` becomes ``"Hardcoded password string"``.
    Bandit's blacklist checks all share the uninformative name ``"blacklist"``,
    so those fall back to the family label, which does say what was flagged.
    """
    if not test_name or test_name.lower() in ("blacklist", "unknown"):
        return _FAMILY_LABEL[family]
    return test_name.replace("_", " ").capitalize()


def _build_finding(
    bandit_result: Dict[str, Any],
) -> Tuple[Optional[Finding], Optional[str]]:
    """
    Build one ``Finding`` from one Bandit result entry.

    Returns ``(finding, note)``.  ``finding`` is None when the entry could not
    be read at all; ``note`` describes anything that had to be assumed, so a
    partially interpretable entry still produces a finding and still says what
    was assumed about it.
    """
    try:
        test_id = str(bandit_result.get("test_id") or "UNKNOWN")
        test_name = str(bandit_result.get("test_name") or "")
        filename = str(bandit_result.get("filename") or "<unknown file>")
        line_number = bandit_result.get("line_number")
        more_info = str(bandit_result.get("more_info") or "")

        # The family drives the plain-language tiers and the redaction decision,
        # so it is resolved once, here, and not recomputed by the caller.
        family = _classify_test(test_id, test_name)
        is_credential_finding = family == "hardcoded_credential"

        # Bandit assigns the severity; it is carried through rather than
        # re-derived.  The ontology's ``spa:Threshold`` individuals classify
        # swept metric values, which is a different operation from relabelling a
        # verdict a tool has already reached.
        raw_severity = str(bandit_result.get("issue_severity") or "").strip().upper()
        note: Optional[str] = None
        if raw_severity in SEVERITY_ORDER and raw_severity != "NONE":
            severity = raw_severity
        else:
            # Bandit emits UNDEFINED for a check that declines to rate the
            # issue.  Such a finding is recorded at LOW and the substitution is
            # reported: guessing upward would inflate the worst severity a
            # management or external projection keys off.
            severity = "LOW"
            note = (
                f"{test_id}: severity {raw_severity or '(absent)'!r} is not a "
                "recognised level; recorded as LOW"
            )

        cwe_info = bandit_result.get("issue_cwe")
        cwe_id = cwe_info.get("id") if isinstance(cwe_info, dict) else None
        cwe_link = cwe_info.get("link") if isinstance(cwe_info, dict) else None

        location = f"{filename}:{line_number}" if line_number else filename
        title = f"{_readable_test_name(test_name, family)} ({test_id}) at {location}"

        technical_detail = {
            "testId": test_id,
            "testName": test_name,
            "filename": filename,
            "lineNumber": line_number,
            "lineRange": bandit_result.get("line_range") or [],
            "columnOffset": bandit_result.get("col_offset"),
            "endColumnOffset": bandit_result.get("end_col_offset"),
            "confidence": str(bandit_result.get("issue_confidence") or "UNKNOWN"),
            "cweId": cwe_id,
            "cweLink": cwe_link,
            "moreInfo": more_info,
        }

        evidence = {
            "code": _redact(str(bandit_result.get("code") or ""), is_credential_finding),
            "issueText": _redact(
                str(bandit_result.get("issue_text") or ""), is_credential_finding
            ),
            # Set so a reader knows the snippet is not a verbatim copy of the
            # source, and does not conclude the file literally contains "****".
            "redacted": is_credential_finding,
        }
        if is_credential_finding:
            evidence["redactionNote"] = REDACTION_NOTE

        steps = [f"Inspect {location} in context and confirm the finding applies."]
        if is_credential_finding:
            # Ordered deliberately: a credential that has been committed is
            # already disclosed, so revocation precedes cleanup.  Deleting the
            # line first leaves the value in version-control history and creates
            # the impression the problem is solved.
            steps += [
                "Revoke and rotate the credential at its issuer before changing "
                "the code — committed history means it must be treated as "
                "already disclosed.",
                "Move the value into a secrets manager or environment variable "
                "and read it at runtime.",
                "Purge the value from version-control history, and check "
                "whether it appears in build logs or artifacts.",
            ]
        else:
            steps.append(_REMEDIATION_ONE_LINE[family])
        if more_info:
            steps.append(f"Bandit's guidance for this check: {more_info}")
        steps.append("Re-run the assessment to confirm the finding is resolved.")

        finding = Finding(
            title=title,
            severity=severity,
            business_impact=_BUSINESS_IMPACT[family],
            technical_detail=technical_detail,
            evidence=evidence,
            remediation={
                "oneLine": _REMEDIATION_ONE_LINE[family],
                "steps": steps,
            },
            # Bandit reports these directly; they are not derived from metric
            # observations, so there is nothing to cite as their basis.
            based_on=[],
        )
        return finding, note

    except Exception as error:  # noqa: BLE001 - one bad row must not lose the run
        return None, f"unreadable Bandit result entry: {error}"


def _scanned_path(intent: Optional[Dict[str, Any]]) -> Optional[str]:
    """The code path the intent asked for, when it named one."""
    if not isinstance(intent, dict):
        return None
    parameters = intent.get("parameters")
    if not isinstance(parameters, dict):
        return None
    code_reference = parameters.get("codeReference")
    if isinstance(code_reference, dict):
        path = code_reference.get("path")
        return str(path) if path else None
    return str(code_reference) if code_reference else None


def _file_count(metrics: Dict[str, Any]) -> int:
    """Number of files Bandit recorded metrics for, excluding the totals row."""
    return sum(1 for key in metrics if key != "_totals")


def _build_scope_limitations(
    raw: Dict[str, Any],
    intent: Optional[Dict[str, Any]],
    findings: List[Finding],
) -> List[str]:
    """
    State the boundaries of what this scan establishes.

    These are derived from the run's own metrics rather than written as fixed
    text, because the numbers are what makes the boundary checkable: "2350
    lines across 31 files" can be reconciled against the target, whereas "a
    subset of the code" cannot.  They are emitted for a clean result too — an
    empty finding list is exactly the case where a reader is most likely to read
    "nothing found" as "nothing to find".
    """
    limitations: List[str] = []
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    totals = metrics.get("_totals") if isinstance(metrics.get("_totals"), dict) else {}

    path = _scanned_path(intent)
    files = _file_count(metrics)
    loc = totals.get("loc")

    scope = (
        f"Only Python source under '{path}' was analysed"
        if path
        else "Only the Python source the scan was pointed at was analysed"
    )
    if files:
        scope += f": {files} file(s)"
        if loc:
            scope += f", {loc} lines of code"
    limitations.append(
        scope + ". Code outside that path, and non-Python code anywhere, "
        "was not examined."
    )

    # A ``# nosec`` comment silences a check.  Left unstated, the suppressions
    # are invisible: the finding count looks like the issue count.
    nosec = totals.get("nosec") or 0
    if nosec:
        limitations.append(
            f"{nosec} issue(s) were suppressed by '# nosec' comments in the "
            "source and are therefore absent from this result. Whether each "
            "suppression is justified was not assessed."
        )

    skipped = totals.get("skipped_tests") or 0
    if skipped:
        limitations.append(
            f"{skipped} test(s) were skipped, so the checks they implement "
            "were not applied."
        )

    errors = raw.get("errors")
    if isinstance(errors, list) and errors:
        limitations.append(
            f"Bandit reported {len(errors)} file-level error(s); those files "
            "were not analysed and may contain issues this result does not show."
        )

    statement = (
        "Static analysis matches code patterns. A finding is not proof that the "
        "issue is reachable or exploitable in this deployment, and an empty "
        "result is not proof that no vulnerability exists — only that no "
        "pattern Bandit checks for was matched."
    )
    low_confidence = sum(
        1 for f in findings if f.technical_detail.get("confidence") == "LOW"
    )
    if low_confidence:
        statement += (
            f" {low_confidence} of the findings reported here carry LOW "
            "confidence from the tool and are correspondingly more likely to be "
            "false positives."
        )
    limitations.append(statement)

    return limitations


def _build_external_scope_statement(raw: Dict[str, Any]) -> List[str]:
    """
    State the same boundaries in wording that may leave the organisation.

    Not derived from ``_build_scope_limitations``: the internal wording names the
    scanned path, the file count and the line count precisely because those make
    the boundary checkable, and a released artifact that carries them describes
    the shape of a customer's codebase.  What translates is the boundary's kind —
    Python source only, pattern matching only, suppressions not reviewed — which
    is what stops a reader over-reading a clean verdict.
    """
    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    totals = metrics.get("_totals") if isinstance(metrics.get("_totals"), dict) else {}

    statement = [
        "The assessment analysed Python source code only. Code written in other "
        "languages, third-party dependencies, configuration and deployed "
        "infrastructure were not examined.",
        "The analysis is static pattern matching. It does not establish that a "
        "reported issue is reachable in operation, and a result with no findings "
        "means no checked pattern was matched rather than that no vulnerability "
        "exists.",
    ]
    # Stated without the count.  That a suppression mechanism was in play is a
    # material qualification of "clean"; how many times it was used describes the
    # codebase, so it stays internal.
    if totals.get("nosec"):
        statement.append(
            "Some checks were suppressed in the source by explicit annotation "
            "and their findings are therefore absent from this result. Whether "
            "those suppressions are justified was not assessed."
        )
    if totals.get("skipped_tests"):
        statement.append(
            "Not every check the tool implements was applied in this run."
        )
    errors = raw.get("errors")
    if isinstance(errors, list) and errors:
        statement.append(
            "Some files could not be parsed and were not analysed; this result "
            "does not cover them."
        )
    return statement


def normalize(
    raw_result: Dict[str, Any],
    intent: Optional[Dict[str, Any]] = None,
) -> FactModel:
    """
    Normalise a Bandit static code analysis result into a ``FactModel``.

    Parameters
    ----------
    raw_result : dict
        The result returned by ``run_bandit_assessment`` -- an envelope with
        ``status``, ``issue_summary``, and optionally ``raw`` containing
        Bandit's full JSON output.
    intent : dict, optional
        The originating intent. Its ``parameters.codeReference.path`` and
        ``criteria`` are recorded as context when present.

    Returns
    -------
    FactModel
        Always returned. A parsing problem is recorded in
        ``normalization_error`` rather than raised, so a completed assessment
        is never lost to a malformed result entry.

    Notes
    -----
    Severity mapping: Bandit's severity labels (HIGH, MEDIUM, LOW, and
    sometimes UNDEFINED) are mapped onto the fact model's vocabulary. An
    unrecognised or UNDEFINED severity is mapped to LOW and recorded in
    ``normalization_error``. Severity is NOT re-derived from ontology
    thresholds — those thresholds are for swept metrics, not for
    re-classifying tool verdicts.
    """

    # Criteria coverage, resolved on every path including failure paths.
    def _coverage(produced_evidence: bool) -> Dict[str, Any]:
        return coverage_for_intent(
            intent, SKILL_NAME, produced_evidence=produced_evidence
        )

    if not isinstance(raw_result, dict):
        return FactModel(
            shape="findingList",
            skill=SKILL_NAME,
            status="INCONCLUSIVE",
            regulatory_coverage=_coverage(False),
            normalization_error=(
                f"expected a Bandit result object, received {type(raw_result).__name__}"
            ),
        )

    raw_status = str(raw_result.get("status", "")).upper()
    if raw_status in {"ERROR", "FAILED", "FAILURE"}:
        return FactModel(
            shape="findingList",
            skill=SKILL_NAME,
            status="FAILED",
            regulatory_coverage=_coverage(False),
            normalization_error=str(
                raw_result.get("message")
                or raw_result.get("error")
                or "Bandit reported a failure"
            ),
        )

    # Check for the raw key
    raw = raw_result.get("raw")
    if not isinstance(raw, dict):
        # Bandit wrapper did not retain findings, only counts.
        return FactModel(
            shape="findingList",
            skill=SKILL_NAME,
            status="INCONCLUSIVE",
            method={
                "assessmentShape": "findingList",
                "tool": "Bandit",
                "issueSummary": raw_result.get("issue_summary", {}),
                "note": "Wrapper did not retain Bandit's raw findings.",
            },
            regulatory_coverage=_coverage(False),
            normalization_error=(
                "The tool wrapper did not retain Bandit's full findings, so "
                "only summary counts are available. Individual findings cannot "
                "be reported."
            ),
        )

    results = raw.get("results", [])
    if not isinstance(results, list):
        return FactModel(
            shape="findingList",
            skill=SKILL_NAME,
            status="INCONCLUSIVE",
            regulatory_coverage=_coverage(False),
            normalization_error="Bandit 'results' field is not a list.",
        )

    # One finding per Bandit result.  An entry that cannot be read is skipped
    # and reported; the remaining findings are still normalised, because losing
    # eight readable findings to one malformed row would be the worse failure.
    findings: List[Finding] = []
    problems: List[str] = []

    for index, entry in enumerate(results):
        if not isinstance(entry, dict):
            problems.append(
                f"result[{index}] is {type(entry).__name__}, not an object; skipped"
            )
            continue
        finding, note = _build_finding(entry)
        if note:
            problems.append(note)
        if finding is not None:
            findings.append(finding)

    # Counts are derived from the findings actually built rather than copied from
    # ``issue_summary``, so the two can be reconciled: a mismatch between them
    # means rows were dropped, and that is visible instead of papered over.
    severity_counts: Dict[str, int] = {}
    confidence_counts: Dict[str, int] = {}
    for finding in findings:
        severity_counts[finding.severity] = severity_counts.get(finding.severity, 0) + 1
        confidence = str(finding.technical_detail.get("confidence") or "UNKNOWN")
        confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1

    metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
    totals = metrics.get("_totals") if isinstance(metrics.get("_totals"), dict) else {}

    method: Dict[str, Any] = {
        "assessmentShape": "findingList",
        "tool": "Bandit",
        "findingCount": len(findings),
        "severityCounts": severity_counts,
        "confidenceCounts": confidence_counts,
        "linesOfCode": totals.get("loc"),
        "filesAnalysed": _file_count(metrics),
        "scannedPath": _scanned_path(intent),
        "suppressedByNosec": totals.get("nosec") or 0,
        "skippedTests": totals.get("skipped_tests") or 0,
        # Bandit's own verdict string, recorded next to the field it came from so
        # a reader can see it is the tool's judgement and not a derived one.
        "toolVerdictField": "assessment",
        "toolVerdict": raw_result.get("assessment"),
        # The counts the wrapper computed, kept alongside ours to make the
        # reconciliation above possible without re-reading the raw output.
        "toolIssueSummary": raw_result.get("issue_summary") or {},
    }
    criteria = intent.get("criteria") if isinstance(intent, dict) else None
    if criteria:
        method["criteria"] = criteria

    # Zero findings with a successful run is a real clean result, not a
    # degradation: the scan ran and matched nothing.  The scope limitations
    # below are what keep that from reading as "there is nothing to find".
    return FactModel(
        shape="findingList",
        skill=SKILL_NAME,
        status="SUCCESS",
        findings=findings,
        # A findingList carries no swept metric, so there is no observation to
        # record and no aggregate to summarise.  Inventing one would present a
        # count as a measurement.
        observations=[],
        metric_summaries=[],
        scope_limitations=_build_scope_limitations(raw, intent, findings),
        external_scope_statement=_build_external_scope_statement(raw),
        method=method,
        regulatory_coverage=_coverage(True),
        normalization_error="; ".join(problems) if problems else None,
    )
