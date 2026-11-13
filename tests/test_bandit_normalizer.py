# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Tests for the Bandit static-code normaliser.

Run with the stdlib runner (no pytest dependency required)::

    python -m unittest discover -s tests -v

``OBSERVED_REPORT`` is trimmed from a real Bandit run over this repository.
The credential in it is a stand-in shaped like the one that was actually
committed to ``fetch-token.py`` and has since been rotated — same format, so
Bandit's B105 check still matches it and still prints it in cleartext, which is
what makes the leak tests meaningful.  Every assertion about masking below
fails if the normalizer stops redacting, which is the failure mode with
consequences outside the test suite.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.bandit_normalizer import (  # noqa: E402
    SKILL_NAME,
    _classify_test,
    normalize,
)

# The literal Bandit reported.  Never assert on this being *present*; it exists
# so the tests can assert it is absent from everything the normalizer produces.
SECRET = "aBn4T~L_Qwe-JpX2V83m7RfKUcqZQVXr2ZTPnvLj"
CLIENT_ID = "969b2b47-d5a3-4bc6-a802-e4cd647b396c"

CREDENTIAL_RESULT = {
    "code": (
        f'13 CLIENT_ID = "{CLIENT_ID}"\n'
        f'14 CLIENT_SECRET = "{SECRET}"  # Replace with your actual client secret\n'
        '15 SCOPE = f"{CLIENT_ID}/.default"\n'
    ),
    "col_offset": 16,
    "end_col_offset": 58,
    "filename": "./fetch-token.py",
    "issue_confidence": "MEDIUM",
    "issue_cwe": {"id": 259, "link": "https://cwe.mitre.org/data/definitions/259.html"},
    "issue_severity": "LOW",
    "issue_text": f"Possible hardcoded password: '{SECRET}'",
    "line_number": 14,
    "line_range": [14],
    "more_info": "https://bandit.readthedocs.io/en/1.9.4/plugins/b105_hardcoded_password_string.html",
    "test_id": "B105",
    "test_name": "hardcoded_password_string",
}

SUBPROCESS_RESULT = {
    "code": "42     subprocess.run(cmd, shell=True)\n",
    "filename": "./tools/trivy_scan.py",
    "issue_confidence": "HIGH",
    "issue_cwe": {"id": 78, "link": "https://cwe.mitre.org/data/definitions/78.html"},
    "issue_severity": "MEDIUM",
    "issue_text": "subprocess call with shell=True identified, security issue.",
    "line_number": 42,
    "line_range": [42],
    "test_id": "B602",
    "test_name": "subprocess_popen_with_shell_equals_true",
}

SQL_RESULT = {
    "code": '88     query = "SELECT * FROM reports WHERE id = %s" % report_id\n',
    "filename": "./orchestrator/store.py",
    "issue_confidence": "LOW",
    "issue_severity": "MEDIUM",
    "issue_text": "Possible SQL injection vector through string-based query construction.",
    "line_number": 88,
    "line_range": [88],
    "test_id": "B608",
    "test_name": "hardcoded_sql_expressions",
}

OBSERVED_REPORT = {
    "errors": [],
    "generated_at": "2026-08-06T09:14:22Z",
    "metrics": {
        "_totals": {
            "CONFIDENCE.HIGH": 1,
            "CONFIDENCE.LOW": 1,
            "CONFIDENCE.MEDIUM": 1,
            "SEVERITY.LOW": 1,
            "SEVERITY.MEDIUM": 2,
            "loc": 6535,
            "nosec": 0,
            "skipped_tests": 0,
        },
        "./fetch-token.py": {"loc": 30},
        "./tools/trivy_scan.py": {"loc": 400},
        "./orchestrator/store.py": {"loc": 220},
    },
    "results": [CREDENTIAL_RESULT, SUBPROCESS_RESULT, SQL_RESULT],
}

INTENT = {
    "parameters": {"codeReference": {"path": "."}},
    "criteria": ["iso27001", "internal_policy:v2"],
}


def _envelope(raw, **overrides):
    envelope = {
        "status": "SUCCESS",
        "assessment": "issues found",
        "issue_summary": {"SEVERITY.LOW": 1, "SEVERITY.MEDIUM": 2},
        "raw": raw,
    }
    envelope.update(overrides)
    return envelope


def _facts(raw=None, intent=INTENT, **overrides):
    return normalize(_envelope(raw if raw is not None else OBSERVED_REPORT, **overrides),
                     intent=intent)


def _by_test_id(facts, test_id):
    return next(
        f for f in facts.findings if f.technical_detail.get("testId") == test_id
    )


class ClassificationTest(unittest.TestCase):
    """
    Test IDs decide the family; names are only a fallback.

    This ordering is the fix for a real defect.  All of Bandit's B4xx import
    checks report ``test_name="blacklist"``, so a name-first classifier cannot
    tell ``B404`` (subprocess import) from any other blacklisted import, and
    ``B608`` (``hardcoded_sql_expressions``) matches "hardcoded" and was filed
    as a credential finding — which would have applied credential remediation
    steps, including "rotate the value", to a SQL string.
    """

    def test_blacklist_checks_are_resolved_by_id_not_name(self):
        self.assertEqual(_classify_test("B404", "blacklist"), "subprocess_shell")

    def test_sql_is_not_mistaken_for_a_credential(self):
        self.assertEqual(
            _classify_test("B608", "hardcoded_sql_expressions"), "sql_injection"
        )

    def test_credential_checks_classify_as_credentials(self):
        for test_id in ("B105", "B106", "B107"):
            with self.subTest(test_id=test_id):
                self.assertEqual(
                    _classify_test(test_id, "hardcoded_password_string"),
                    "hardcoded_credential",
                )

    def test_an_unmapped_id_falls_back_to_the_name(self):
        self.assertEqual(
            _classify_test("B9999", "some_yaml_load_check"), "yaml_load"
        )

    def test_an_unrecognisable_check_is_generic_not_dropped(self):
        # A future Bandit release adding a check must still produce a finding;
        # silently discarding it would understate the result.
        self.assertEqual(_classify_test("B9999", "brand_new_check"), "generic")


class SecretMaskingTest(unittest.TestCase):
    """
    No credential value reaches the fact model.

    Masking happens here, at normalisation, rather than in the audience
    projection: the facts are stored and re-projected later, so a secret
    admitted once outlives any judgement about who should see it.
    """

    def setUp(self):
        self.facts = _facts()
        self.serialised = repr(self.facts.to_dict())

    def test_the_credential_value_is_absent_from_the_whole_fact_model(self):
        self.assertNotIn(SECRET, self.serialised)

    def test_context_lines_are_masked_too(self):
        # Bandit flagged line 14 only, but printed 13 and 15 as context.  The
        # client id on line 13 is not what the finding is about and would
        # survive a mask that trusted the tool's line range.
        self.assertNotIn(CLIENT_ID, self.serialised)

    def test_the_issue_text_is_masked_as_well_as_the_snippet(self):
        # Bandit repeats the value in its prose ("Possible hardcoded password:
        # '<secret>'"), so masking the code block alone is not enough.
        finding = _by_test_id(self.facts, "B105")
        self.assertNotIn(SECRET, finding.evidence["issueText"])

    def test_the_reader_is_told_the_snippet_was_altered(self):
        finding = _by_test_id(self.facts, "B105")
        self.assertTrue(finding.evidence["redacted"])
        self.assertIn("masked", finding.evidence["redactionNote"])

    def test_the_location_survives_so_the_finding_stays_actionable(self):
        # Masking must not cost the reader the ability to check the finding:
        # the file and line are what make the redaction acceptable.
        finding = _by_test_id(self.facts, "B105")
        self.assertEqual(finding.technical_detail["filename"], "./fetch-token.py")
        self.assertEqual(finding.technical_detail["lineNumber"], 14)


class FindingConstructionTest(unittest.TestCase):
    """Each finding carries all three detail tiers, populated independently."""

    def setUp(self):
        self.facts = _facts()

    def test_every_result_becomes_a_finding(self):
        self.assertEqual(len(self.facts.findings), 3)

    def test_severity_is_taken_from_bandit_not_re_derived(self):
        self.assertEqual(_by_test_id(self.facts, "B105").severity, "LOW")
        self.assertEqual(_by_test_id(self.facts, "B602").severity, "MEDIUM")

    def test_worst_severity_is_the_highest_present(self):
        self.assertEqual(self.facts.worst_severity, "MEDIUM")

    def test_the_three_tiers_are_separate_fields(self):
        finding = _by_test_id(self.facts, "B602")
        self.assertTrue(finding.business_impact)
        self.assertTrue(finding.technical_detail)
        self.assertTrue(finding.evidence)

    def test_business_impact_avoids_the_tool_vocabulary(self):
        # The management tier is a field selection, so this text is what a
        # non-technical reader sees unmediated.  A rule id in it defeats that.
        for finding in self.facts.findings:
            with self.subTest(title=finding.title):
                self.assertNotIn("B10", finding.business_impact or "")
                self.assertNotIn("shell=True", finding.business_impact or "")

    def test_confidence_is_recorded_so_a_reader_can_discount_a_finding(self):
        self.assertEqual(
            _by_test_id(self.facts, "B608").technical_detail["confidence"], "LOW"
        )

    def test_remediation_is_specific_to_the_finding_family(self):
        credential = _by_test_id(self.facts, "B105").remediation
        sql = _by_test_id(self.facts, "B608").remediation
        self.assertNotEqual(credential["oneLine"], sql["oneLine"])
        # A committed credential must be rotated; that step is meaningless for
        # a SQL string and would be noise if the family were misclassified.
        self.assertIn("otate", " ".join(credential["steps"]))

    def test_a_malformed_result_is_reported_not_fatal(self):
        raw = dict(OBSERVED_REPORT, results=[CREDENTIAL_RESULT, "not an object"])
        facts = _facts(raw)
        self.assertEqual(facts.status, "SUCCESS")
        self.assertEqual(len(facts.findings), 1)
        self.assertIsNotNone(facts.normalization_error)

    def test_a_result_missing_severity_still_yields_a_finding(self):
        stripped = {k: v for k, v in SUBPROCESS_RESULT.items() if k != "issue_severity"}
        facts = _facts(dict(OBSERVED_REPORT, results=[stripped]))
        self.assertEqual(len(facts.findings), 1)


class MethodTest(unittest.TestCase):
    """The method block must let a reader reconcile the counts."""

    def setUp(self):
        self.facts = _facts()

    def test_counts_are_derived_from_the_findings_built(self):
        self.assertEqual(
            self.facts.method["severityCounts"], {"LOW": 1, "MEDIUM": 2}
        )
        self.assertEqual(self.facts.method["findingCount"], 3)

    def test_the_tools_own_summary_is_kept_alongside_for_comparison(self):
        # Derived counts and Bandit's own are both recorded so a discrepancy
        # between them is visible rather than resolved silently in favour of one.
        self.assertIn("toolIssueSummary", self.facts.method)
        self.assertEqual(
            self.facts.method["toolIssueSummary"]["SEVERITY.MEDIUM"], 2
        )

    def test_coverage_metrics_are_carried(self):
        self.assertEqual(self.facts.method["linesOfCode"], 6535)
        self.assertEqual(self.facts.method["filesAnalysed"], 3)

    def test_the_tool_verdict_is_labelled_as_the_tools(self):
        self.assertEqual(self.facts.method["toolVerdictField"], "assessment")
        self.assertEqual(self.facts.method["toolVerdict"], "issues found")

    def test_no_observations_are_invented_for_a_finding_list(self):
        # A finding count is not a measurement; presenting one as an
        # observation would let it be aggregated as though it were.
        self.assertEqual(self.facts.observations, [])
        self.assertEqual(self.facts.metric_summaries, [])

    def test_the_shape_and_skill_are_declared(self):
        self.assertEqual(self.facts.shape, "findingList")
        self.assertEqual(self.facts.skill, SKILL_NAME)


class ScopeLimitationTest(unittest.TestCase):
    """A clean scan is the case where the stated bounds matter most."""

    def test_limitations_are_emitted_for_a_clean_result_too(self):
        clean = dict(
            OBSERVED_REPORT,
            results=[],
            metrics={"_totals": {"loc": 100, "nosec": 0, "skipped_tests": 0}, "a.py": {}},
        )
        facts = _facts(clean)
        self.assertEqual(facts.findings, [])
        self.assertTrue(facts.scope_limitations)

    def test_pattern_matching_is_stated_as_a_limit_on_the_conclusion(self):
        joined = " ".join(_facts().scope_limitations)
        self.assertIn("pattern", joined.lower())

    def test_the_scanned_path_is_named_internally(self):
        joined = " ".join(_facts().scope_limitations)
        self.assertIn("Python source", joined)

    def test_suppressions_are_disclosed(self):
        raw = dict(
            OBSERVED_REPORT,
            metrics={
                "_totals": {"loc": 100, "nosec": 4, "skipped_tests": 0},
                "a.py": {},
            },
        )
        joined = " ".join(_facts(raw).scope_limitations)
        self.assertIn("4 issue(s) were suppressed", joined)

    def test_unparsed_files_are_disclosed(self):
        raw = dict(OBSERVED_REPORT, errors=[{"filename": "./broken.py"}])
        joined = " ".join(_facts(raw).scope_limitations)
        self.assertIn("error", joined.lower())

    def test_low_confidence_findings_are_flagged_in_the_scope(self):
        joined = " ".join(_facts().scope_limitations)
        self.assertIn("LOW", joined)


class ExternalScopeStatementTest(unittest.TestCase):
    """
    The external wording is written, not derived from the internal wording.

    ``scope_limitations`` names the path, the file count and the line count
    precisely so a colleague can reconcile them against the target.  Those are
    what must not appear in an artifact that leaves the organisation, so the
    external statement is a separate opt-in field rather than a filtered copy.
    """

    def setUp(self):
        raw = dict(
            OBSERVED_REPORT,
            errors=[{"filename": "./broken.py"}],
            metrics={
                "_totals": {"loc": 6535, "nosec": 4, "skipped_tests": 2},
                "./secret-project/a.py": {},
            },
        )
        self.facts = _facts(
            raw, intent={"parameters": {"codeReference": {"path": "/internal/secret-project"}}}
        )

    def test_an_external_statement_is_offered(self):
        self.assertTrue(self.facts.external_scope_statement)

    def test_it_names_no_path_file_count_or_line_count(self):
        joined = " ".join(self.facts.external_scope_statement)
        for leak in ("secret-project", "6535", "/internal"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, joined)

    def test_it_does_not_quantify_the_suppressions(self):
        # That a suppression mechanism was in play qualifies "clean" and must
        # be said; how many times it was used describes the codebase.
        joined = " ".join(self.facts.external_scope_statement)
        self.assertIn("suppressed", joined)
        self.assertNotIn("4", joined)

    def test_it_keeps_the_limit_on_what_a_clean_result_means(self):
        joined = " ".join(self.facts.external_scope_statement).lower()
        self.assertIn("pattern", joined)
        self.assertIn("python", joined)

    def test_it_is_not_a_copy_of_the_internal_wording(self):
        self.assertNotEqual(
            self.facts.external_scope_statement, self.facts.scope_limitations
        )


class CoverageTest(unittest.TestCase):
    """Criterion coverage is resolved against the ontology, not asserted."""

    def test_a_named_criterion_the_skill_can_evidence_is_assessed(self):
        criteria = _facts().regulatory_coverage["criteria"]
        iso = next(c for c in criteria if c["criterion"] == "iso27001")
        self.assertEqual(iso["status"], "assessed")

    def test_an_assessed_criterion_still_states_what_it_did_not_cover(self):
        criteria = _facts().regulatory_coverage["criteria"]
        iso = next(c for c in criteria if c["criterion"] == "iso27001")
        self.assertTrue(iso["unassessedRequirements"])

    def test_an_unknown_token_is_reported_not_dropped(self):
        criteria = _facts().regulatory_coverage["criteria"]
        policy = next(c for c in criteria if c["criterion"] == "internal_policy:v2")
        self.assertEqual(policy["status"], "unrecognised")


class DegradedInputTest(unittest.TestCase):
    """A normalizer degrades rather than raising; a lost result is worse."""

    def test_a_failed_run_is_reported_as_failed(self):
        facts = normalize({"status": "FAILED", "error": "bandit not installed"})
        self.assertEqual(facts.status, "FAILED")
        self.assertEqual(facts.findings, [])

    def test_a_result_without_raw_output_is_inconclusive_not_clean(self):
        # Zero findings because the output is missing must never be reported as
        # zero findings because nothing was found.
        facts = normalize({"status": "SUCCESS", "assessment": "clean"})
        self.assertEqual(facts.status, "INCONCLUSIVE")
        self.assertIsNotNone(facts.normalization_error)

    def test_an_empty_result_list_with_metrics_is_a_real_clean_result(self):
        facts = _facts(
            {"results": [], "metrics": {"_totals": {"loc": 10}, "a.py": {}}, "errors": []}
        )
        self.assertEqual(facts.status, "SUCCESS")
        self.assertEqual(facts.worst_severity, "NONE")
        self.assertIsNone(facts.normalization_error)

    def test_normalisation_is_deterministic(self):
        self.assertEqual(_facts().to_dict(), _facts().to_dict())


if __name__ == "__main__":
    unittest.main()
