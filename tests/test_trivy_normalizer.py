# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Tests for the Trivy normaliser.

Run with the stdlib runner (no pytest dependency required)::

    python -m unittest discover -s tests -v

``OBSERVED_REPORT`` is trimmed from ``storage/scan-fs-intent-fs-scan-002.json``,
a real filesystem scan of this repository.  The secret finding in it is the
regression fixture for a specific defect: Trivy masked the ``CLIENT_SECRET``
line it matched but returned the ``TENANT_ID`` and ``CLIENT_ID`` assignments on
the adjacent context lines verbatim.  A normalizer that trusts ``maskedByTool``
therefore copies two credentials into the stored facts.  The values below are
the ones that were really committed and have since been rotated; they are kept
literal so the leak assertions test something.

Two boundaries recur in these tests and are worth naming once:

* Trivy is invoked at ``HIGH,CRITICAL`` only.  A zero-finding result establishes
  "nothing at those two levels", never "clean", so the filter is the first thing
  the scope must state.
* Severity is Trivy's, carried through.  The ontology's ``spa:Threshold``
  individuals classify swept metric values, which is a different operation from
  relabelling a verdict the tool already reached.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.trivy_normalizer import (  # noqa: E402
    SKILL_NAME_BY_ASSESSMENT_TYPE,
    _normalize_severity,
    normalize,
)

TENANT_ID = "92e84ceb-fbfd-47ab-be52-080c6b87953f"
CLIENT_ID = "969b2b47-d5a3-4bc6-a802-e4cd647b396c"

SECRET_RESULT = {
    "Target": "fetch-token.py",
    "Class": "secret",
    "Secrets": [
        {
            "RuleID": "azure-entra-client-secret",
            "Category": "Azure",
            "Severity": "CRITICAL",
            "Title": "Azure Entra ID Client Secret",
            "StartLine": 14,
            "EndLine": 14,
            "Code": {
                "Lines": [
                    {
                        "Number": 12,
                        "Content": f'TENANT_ID = "{TENANT_ID}"',
                        "IsCause": False,
                    },
                    {
                        "Number": 13,
                        "Content": f'CLIENT_ID = "{CLIENT_ID}"',
                        "IsCause": False,
                    },
                    {
                        "Number": 14,
                        "Content": 'CLIENT_SECRET = "****"  # Replace with your actual client secret',
                        "IsCause": True,
                    },
                    {
                        "Number": 15,
                        "Content": 'SCOPE = f"{CLIENT_ID}/.default"',
                        "IsCause": False,
                    },
                ]
            },
            "Match": 'CLIENT_SECRET = "****"  # Replace with your actual client secret',
            "Offset": 484,
        }
    ],
}

MISCONFIG_RESULT = {
    "Target": "Dockerfile",
    "Class": "config",
    "Type": "dockerfile",
    "MisconfSummary": {"Successes": 19, "Failures": 1},
    "Misconfigurations": [
        {
            "Type": "Dockerfile Security Check",
            "ID": "DS-0002",
            "Title": "Image user should not be 'root'",
            "Description": (
                "Running containers with 'root' user can lead to a container "
                "escape situation."
            ),
            "Message": "Specify at least 1 USER command",
            "Resolution": "Add 'USER <non root user name>' line to the Dockerfile",
            "Severity": "HIGH",
            "PrimaryURL": "https://avd.aquasec.com/misconfig/ds002",
            "Status": "FAIL",
            "CauseMetadata": {"Provider": "Dockerfile", "Service": "general"},
        }
    ],
}

VULN_RESULT = {
    "Target": "requirements.txt",
    "Class": "lang-pkgs",
    "Type": "pip",
    "Vulnerabilities": [
        {
            "VulnerabilityID": "CVE-2024-99999",
            "PkgName": "requests",
            "InstalledVersion": "2.19.0",
            "FixedVersion": "2.31.0",
            "Status": "fixed",
            "Severity": "HIGH",
            "Title": "Session fixation in requests",
            "Description": "A crafted redirect can leak the Authorization header.",
            "PrimaryURL": "https://avd.aquasec.com/nvd/cve-2024-99999",
            "CweIDs": ["CWE-200"],
            "CVSS": {
                "nvd": {"V3Score": 7.5},
                "redhat": {"V3Score": 8.1},
            },
            "References": [f"https://example.invalid/ref{n}" for n in range(9)],
        }
    ],
}

OBSERVED_REPORT = {
    "SchemaVersion": 2,
    "Trivy": {"Version": "0.72.0"},
    "ArtifactName": ".",
    "ArtifactType": "repository",
    "Metadata": {"RepoURL": "https://github.com/INTEND-Project/inTrust.git"},
    "Results": [MISCONFIG_RESULT, SECRET_RESULT, VULN_RESULT],
}


def _envelope(report=None, **overrides):
    envelope = {
        "status": "SUCCESS",
        "assessment_type": "filesystem_security",
        "tool": "Trivy",
        "version": "0.72.0",
        "target": ".",
        "severityFilter": "HIGH,CRITICAL",
        "scanners": "vuln,secret,misconfig",
        "assessment": "issues found",
        "raw": OBSERVED_REPORT if report is None else report,
    }
    envelope.update(overrides)
    return envelope


def _facts(report=None, intent=None, **overrides):
    return normalize(_envelope(report, **overrides), intent=intent)


def _by_kind(facts, kind):
    return [
        f for f in facts.findings if f.technical_detail.get("findingKind") == kind
    ]


class SkillResolutionTest(unittest.TestCase):
    """
    The skill name is derived from the assessment type, never guessed.

    Criterion coverage is looked up by skill name, so a plausible-looking
    fallback would resolve every criterion to "not assessed" while presenting a
    successful lookup — worse than declining to resolve at all.
    """

    def test_each_assessment_type_maps_to_its_skill(self):
        for assessment_type, skill in SKILL_NAME_BY_ASSESSMENT_TYPE.items():
            with self.subTest(assessment_type=assessment_type):
                facts = _facts(assessment_type=assessment_type)
                self.assertEqual(facts.skill, skill)

    def test_an_unknown_assessment_type_resolves_to_no_skill(self):
        facts = _facts(assessment_type="quantum_security")
        self.assertEqual(facts.skill, "trivy")
        self.assertIn("not one of", facts.normalization_error)

    def test_an_unknown_type_resolves_no_coverage_rather_than_false_coverage(self):
        facts = _facts(
            assessment_type="quantum_security", intent={"criteria": ["iso27001"]}
        )
        for coverage in facts.regulatory_coverage["criteria"]:
            with self.subTest(criterion=coverage["criterion"]):
                self.assertNotEqual(coverage["status"], "assessed")


class SecretMaskingTest(unittest.TestCase):
    """
    No credential reaches the fact model, including ones Trivy did not flag.

    Masking is applied here, at normalisation, and not in the audience
    projection: the facts are stored and re-projected later, so a value admitted
    once outlives any judgement about who should see it.
    """

    def setUp(self):
        self.facts = _facts()
        self.serialised = repr(self.facts.to_dict())

    def test_context_line_credentials_are_masked(self):
        # The defect this suite exists for: Trivy masked line 14 and returned
        # lines 12 and 13 verbatim.
        for leak in (TENANT_ID, CLIENT_ID):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, self.serialised)

    def test_the_tools_own_masking_is_recorded_as_insufficient(self):
        # Both flags are set: the reader needs to know the snippet is not a
        # verbatim copy, and that the mask is partly ours rather than the tool's.
        evidence = _by_kind(self.facts, "secret")[0].evidence
        self.assertTrue(evidence["maskedByTool"])
        self.assertTrue(evidence["maskedDuringNormalisation"])

    def test_the_match_string_is_masked_too(self):
        # ``Match`` repeats the matched line, so masking only ``Code.Lines``
        # would leave a second copy behind.
        evidence = _by_kind(self.facts, "secret")[0].evidence
        self.assertNotIn(TENANT_ID, evidence["match"])
        self.assertNotIn(CLIENT_ID, evidence["match"])

    def test_the_location_survives_the_masking(self):
        finding = _by_kind(self.facts, "secret")[0]
        self.assertEqual(finding.technical_detail["startLine"], 14)
        self.assertEqual(finding.technical_detail["target"], "fetch-token.py")

    def test_the_remediation_leads_with_rotation_not_deletion(self):
        # By the time a scanner finds a committed credential it is disclosed;
        # deleting the line only hides it from the next scan.
        steps = " ".join(_by_kind(self.facts, "secret")[0].remediation["steps"])
        self.assertIn("Revoke", steps)


class FindingKindTest(unittest.TestCase):
    """Each of Trivy's four arrays has its own schema and its own converter."""

    def setUp(self):
        self.facts = _facts()

    def test_all_three_present_kinds_are_extracted(self):
        self.assertEqual(len(_by_kind(self.facts, "misconfiguration")), 1)
        self.assertEqual(len(_by_kind(self.facts, "secret")), 1)
        self.assertEqual(len(_by_kind(self.facts, "vulnerability")), 1)

    def test_severity_is_trivys_own(self):
        self.assertEqual(_by_kind(self.facts, "secret")[0].severity, "CRITICAL")
        self.assertEqual(
            _by_kind(self.facts, "misconfiguration")[0].severity, "HIGH"
        )

    def test_worst_severity_is_the_highest_across_kinds(self):
        self.assertEqual(self.facts.worst_severity, "CRITICAL")

    def test_the_highest_cvss_score_across_sources_is_recorded(self):
        # Trivy reports a score per scoring source; taking the first would
        # understate the finding depending on dict ordering.
        detail = _by_kind(self.facts, "vulnerability")[0].technical_detail
        self.assertEqual(detail["cvssScore"], 8.1)

    def test_the_fix_version_is_carried_because_it_is_the_action(self):
        detail = _by_kind(self.facts, "vulnerability")[0].technical_detail
        self.assertEqual(detail["fixedVersion"], "2.31.0")

    def test_reference_truncation_is_disclosed_not_silent(self):
        evidence = _by_kind(self.facts, "vulnerability")[0].evidence
        self.assertEqual(len(evidence["references"]), 5)
        self.assertTrue(evidence["referencesTruncated"])

    def test_a_licence_finding_reports_trivys_category_not_a_legal_verdict(self):
        # Whether a licence obligation conflicts with how the product ships is a
        # legal question; the normalizer reports the scanner's category and says
        # the question is not decided here.
        report = {
            "Results": [
                {
                    "Target": "vendor/",
                    "Class": "license",
                    "Licenses": [
                        {
                            "Name": "GPL-3.0",
                            "Category": "notice",
                            "Severity": "HIGH",
                            "PkgName": "somepkg",
                            "Confidence": 0.9,
                        }
                    ],
                }
            ]
        }
        finding = _by_kind(_facts(report), "license")[0]
        self.assertEqual(finding.technical_detail["category"], "notice")
        self.assertNotIn("Restricted", finding.title)
        self.assertIn("not decided here", finding.business_impact)

    def test_business_impact_is_free_of_the_tool_vocabulary(self):
        # The management tier is a field selection, so this text reaches a
        # non-technical reader unmediated.
        for finding in self.facts.findings:
            with self.subTest(title=finding.title):
                self.assertNotIn("CauseMetadata", finding.business_impact or "")
                self.assertNotIn("V3Score", finding.business_impact or "")

    def test_an_unreadable_entry_costs_only_that_entry(self):
        report = {
            "Results": [
                MISCONFIG_RESULT,
                {"Target": "x", "Class": "secret", "Secrets": ["not an object"]},
            ]
        }
        facts = _facts(report)
        self.assertEqual(facts.status, "SUCCESS")
        self.assertEqual(len(facts.findings), 1)
        self.assertIsNotNone(facts.normalization_error)

    def test_a_malformed_results_entry_is_reported_not_fatal(self):
        facts = _facts({"Results": [MISCONFIG_RESULT, "not an object"]})
        self.assertEqual(len(facts.findings), 1)
        self.assertIn("not an object", facts.normalization_error)


class SeverityMappingTest(unittest.TestCase):
    """An unrecognised severity is recorded downward, and the guess is stated."""

    def test_trivy_levels_pass_through(self):
        for level in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
            with self.subTest(level=level):
                self.assertEqual(_normalize_severity(level), (level, None))

    def test_unknown_becomes_low_with_a_note(self):
        severity, note = _normalize_severity("UNKNOWN")
        self.assertEqual(severity, "LOW")
        self.assertIsNotNone(note)

    def test_none_is_not_accepted_from_a_reported_finding(self):
        # NONE is the fact model's "no severity present" sentinel; a finding that
        # exists cannot carry it, or it would vanish from the worst-severity
        # calculation that drives both the management floor and the release gate.
        severity, note = _normalize_severity("NONE")
        self.assertEqual(severity, "LOW")
        self.assertIsNotNone(note)

    def test_an_absent_severity_does_not_inflate_the_result(self):
        severity, _ = _normalize_severity(None)
        self.assertEqual(severity, "LOW")

    def test_the_substitution_reaches_the_normalisation_error(self):
        report = {
            "Results": [
                {
                    "Target": "x",
                    "Class": "config",
                    "Misconfigurations": [{"ID": "X-1", "Severity": "WEIRD"}],
                }
            ]
        }
        facts = _facts(report)
        self.assertIn("WEIRD", facts.normalization_error)


class MethodTest(unittest.TestCase):
    """The method block must let a reader reconcile and re-derive."""

    def setUp(self):
        self.facts = _facts()

    def test_counts_are_derived_from_the_findings_built(self):
        self.assertEqual(self.facts.method["findingCount"], 3)
        self.assertEqual(
            self.facts.method["severityCounts"], {"HIGH": 2, "CRITICAL": 1}
        )

    def test_finding_kinds_are_counted_separately(self):
        self.assertEqual(
            self.facts.method["findingKindCounts"],
            {"misconfiguration": 1, "secret": 1, "vulnerability": 1},
        )

    def test_the_severity_filter_is_recorded_beside_the_limitation_it_causes(self):
        self.assertEqual(self.facts.method["severityFilter"], "HIGH,CRITICAL")
        self.assertFalse(self.facts.method["severityFilterAssumed"])

    def test_an_absent_filter_is_marked_as_assumed(self):
        # Older stored results predate the wrapper recording the filter.  The
        # assumption is usable but must not masquerade as observed.
        envelope = _envelope()
        del envelope["severityFilter"]
        facts = normalize(envelope)
        self.assertTrue(facts.method["severityFilterAssumed"])
        self.assertEqual(facts.method["severityFilter"], "HIGH,CRITICAL")

    def test_the_tool_verdict_is_labelled_as_the_tools(self):
        self.assertEqual(self.facts.method["toolVerdictField"], "assessment")
        self.assertEqual(self.facts.method["toolVerdict"], "issues found")

    def test_no_observations_are_invented_for_a_finding_list(self):
        self.assertEqual(self.facts.observations, [])
        self.assertEqual(self.facts.metric_summaries, [])

    def test_the_shape_is_declared_as_a_finding_list(self):
        self.assertEqual(self.facts.shape, "findingList")


class ScopeLimitationTest(unittest.TestCase):
    """The severity filter is the boundary a clean result most needs stated."""

    def test_the_filter_is_stated_on_every_result(self):
        joined = " ".join(_facts().scope_limitations)
        self.assertIn("HIGH and CRITICAL", joined)

    def test_a_clean_result_still_carries_every_limitation(self):
        facts = _facts({"ArtifactName": ".", "Results": []})
        self.assertEqual(facts.findings, [])
        self.assertEqual(facts.worst_severity, "NONE")
        joined = " ".join(facts.scope_limitations)
        self.assertIn("HIGH", joined)
        self.assertIn("MEDIUM", joined)

    def test_the_uncollected_levels_are_named(self):
        joined = " ".join(_facts().scope_limitations)
        for level in ("MEDIUM", "LOW", "UNKNOWN"):
            with self.subTest(level=level):
                self.assertIn(level, joined)

    def test_disabled_licence_detection_is_disclosed(self):
        # A filesystem scan runs vuln,secret,misconfig.  Left unstated, "no
        # licence findings" would read as a licence review having been done.
        joined = " ".join(_facts().scope_limitations)
        self.assertIn("Licence detection was not", joined)

    def test_database_currency_is_stated_when_known(self):
        report = dict(
            OBSERVED_REPORT,
            Trivy={"Version": "0.72.0", "VulnerabilityDBUpdatedAt": "2026-07-22T00:00:00Z"},
        )
        joined = " ".join(_facts(report).scope_limitations)
        self.assertIn("2026-07-22", joined)

    def test_the_scanner_classes_that_ran_are_stated(self):
        joined = " ".join(_facts().scope_limitations)
        self.assertIn("secret", joined)
        self.assertIn("config", joined)


class ExternalScopeStatementTest(unittest.TestCase):
    """
    The external wording is written, not filtered from the internal wording.

    ``scope_limitations`` names the artifact, the target count and the database
    timestamp so a colleague can reconcile them; an artifact name is routinely an
    internal image or repository path.  The severity filter is the one boundary
    that translates directly, and it is the one that must survive.
    """

    def setUp(self):
        self.facts = _facts(
            dict(OBSERVED_REPORT, ArtifactName="registry.internal/secret-project:1.4"),
            target="registry.internal/secret-project:1.4",
        )

    def test_an_external_statement_is_offered(self):
        self.assertTrue(self.facts.external_scope_statement)

    def test_the_filter_boundary_survives_translation(self):
        joined = " ".join(self.facts.external_scope_statement)
        self.assertIn("HIGH and CRITICAL", joined)

    def test_no_artifact_name_or_repository_url_leaves(self):
        joined = " ".join(self.facts.external_scope_statement)
        for leak in ("secret-project", "registry.internal", "github.com"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, joined)

    def test_no_target_count_or_database_timestamp_leaves(self):
        joined = " ".join(self.facts.external_scope_statement)
        self.assertNotIn("3 scan target", joined)
        self.assertNotIn("2026-", joined)

    def test_it_keeps_the_limit_on_what_no_finding_means(self):
        joined = " ".join(self.facts.external_scope_statement)
        self.assertIn("no finding is not the same as no defect", joined)

    def test_it_is_not_a_copy_of_the_internal_wording(self):
        self.assertNotEqual(
            self.facts.external_scope_statement, self.facts.scope_limitations
        )

    def test_an_unfiltered_scan_says_so_rather_than_naming_absent_levels(self):
        facts = _facts(severityFilter="CRITICAL,HIGH,MEDIUM,LOW,UNKNOWN")
        joined = " ".join(facts.external_scope_statement)
        self.assertIn("all severity levels", joined)


class CoverageTest(unittest.TestCase):
    """Criterion coverage is resolved against the ontology, not asserted."""

    def test_a_criterion_the_skill_can_evidence_is_assessed(self):
        facts = _facts(intent={"criteria": ["nis2", "iso27001"]})
        for coverage in facts.regulatory_coverage["criteria"]:
            with self.subTest(criterion=coverage["criterion"]):
                self.assertEqual(coverage["status"], "assessed")

    def test_an_assessed_criterion_still_states_what_it_did_not_cover(self):
        facts = _facts(intent={"criteria": ["nis2"]})
        nis2 = facts.regulatory_coverage["criteria"][0]
        self.assertTrue(nis2["unassessedRequirements"])
        self.assertIn("of", nis2["note"])

    def test_criteria_nested_under_assessment_are_found(self):
        facts = _facts(intent={"assessment": {"criteria": ["iso27001"]}})
        self.assertEqual(facts.regulatory_coverage["criteriaCount"], 1)

    def test_a_failed_scan_claims_no_coverage(self):
        facts = normalize(
            _envelope(status="FAILED", error="trivy not installed"),
            intent={"criteria": ["iso27001"]},
        )
        for coverage in facts.regulatory_coverage["criteria"]:
            self.assertNotEqual(coverage["status"], "assessed")


class DegradedInputTest(unittest.TestCase):
    """A normalizer degrades rather than raising; a lost result is worse."""

    def test_a_failed_scan_is_reported_as_failed(self):
        facts = normalize(_envelope(status="FAILED", error="trivy not installed"))
        self.assertEqual(facts.status, "FAILED")
        self.assertEqual(facts.findings, [])

    def test_a_result_without_the_raw_report_is_inconclusive_not_clean(self):
        # Zero findings for want of a report must never be reported as zero
        # findings for want of anything to find.
        envelope = _envelope()
        del envelope["raw"]
        facts = normalize(envelope)
        self.assertEqual(facts.status, "INCONCLUSIVE")
        self.assertIsNotNone(facts.normalization_error)

    def test_a_non_dict_result_is_inconclusive(self):
        facts = normalize("not a result")
        self.assertEqual(facts.status, "INCONCLUSIVE")

    def test_an_empty_results_list_is_a_real_clean_result(self):
        facts = _facts({"ArtifactName": ".", "Results": []})
        self.assertEqual(facts.status, "SUCCESS")
        self.assertIsNone(facts.normalization_error)

    def test_normalisation_is_deterministic(self):
        self.assertEqual(_facts().to_dict(), _facts().to_dict())


if __name__ == "__main__":
    unittest.main()
