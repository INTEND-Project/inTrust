# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Tests for audience profiles, projection, and criterion coverage.

Run with the stdlib runner (no pytest dependency required)::

    python -m unittest discover -s tests -v

These tests exist to hold one invariant: **different audiences receive
different views, never different results.**  So most of what is checked here is
agreement between renditions — that the verdict, the worst case, and the
threshold-crossing findings survive every projection, and that whatever a
projection drops is declared rather than silently absent.

The fixture is the same real MIA payload used by ``test_mia_normalizer`` (see
its module docstring for why that payload is the regression case).
"""

import dataclasses
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.criterion_registry import (  # noqa: E402
    CriterionRegistry,
    RegulatorySource,
    Requirement,
    _normalise,
    coverage_for_intent,
    coverage_summary,
    criteria_from_intent,
    resolve_coverage,
)
from orchestrator.criterion_registry import (  # noqa: E402
    load_registry as load_criterion_registry,
)
from orchestrator.report_profile import (  # noqa: E402
    EXTERNAL_ALLOWLIST,
    EXTERNAL_GATES,
    EXTERNAL_VALIDITY_DAYS,
    EXTERNAL_VALIDITY_PERIOD,
    PROFILES,
    REGISTRY,
    band_count,
    band_magnitude,
    effective_disclosure,
    project,
    project_all,
    resolve_profile,
)
from tests.test_mia_normalizer import OBSERVED_SWEEP  # noqa: E402
from tools.mia_normalizer import normalize  # noqa: E402


# --------------------------------------------------------------------------
# A hand-built registry, so coverage tests do not depend on which requirements
# happen to be declared in the ontology today.
# --------------------------------------------------------------------------

_MIA_REQUIREMENT = Requirement(
    iri="urn:test:req:assessed",
    identifier="TEST-Art1",
    label="Security of processing",
    description="Appropriate technical measures.",
    source_reference="Test Art. 1",
    evaluated_by_skills=("mia-privacy",),
)
_MANUAL_REQUIREMENT = Requirement(
    iri="urn:test:req:manual",
    identifier="TEST-Art2",
    label="Data subject rights",
    description="Rights of the data subject.",
    source_reference="Test Art. 2",
    evaluated_by_skills=(),
)

_TEST_REGISTRY = CriterionRegistry(
    {
        "testreg": RegulatorySource(
            iri="urn:test:source:testreg",
            criterion_key="testreg",
            identifier="TESTREG",
            label="Test Regulation",
            source_reference="Test Regulation (EU) 1/2000",
            requirements=(_MIA_REQUIREMENT, _MANUAL_REQUIREMENT),
        ),
        "unevaluable": RegulatorySource(
            iri="urn:test:source:unevaluable",
            criterion_key="unevaluable",
            identifier="UNEVAL",
            label="Unevaluable Standard",
            source_reference="Uneval 1.0",
            requirements=(_MANUAL_REQUIREMENT,),
        ),
    }
)


class CriterionNormalisationTest(unittest.TestCase):
    """Intents write criteria loosely; lookup must not depend on the spelling."""

    def test_case_and_separators_are_ignored(self):
        self.assertEqual(_normalise("  GDPR "), "gdpr")
        self.assertEqual(_normalise("nist-csf"), "nistcsf")
        self.assertEqual(_normalise("ISO 27001"), "iso27001")

    def test_alternate_spellings_reach_the_same_source(self):
        # Normalisation alone does not equate "ISO/IEC 27001" with "iso27001";
        # the registry also indexes each source under its human identifier, and
        # what matters is that both tokens an intent might use resolve.
        registry = load_criterion_registry()
        for tokens in (
            ("gdpr", "GDPR"),
            ("iso27001", "ISO/IEC 27001", "ISO 27001"),
            ("nistcsf", "NIST CSF"),
            ("tmf-tr2921", "TMF TR2921"),
        ):
            with self.subTest(tokens=tokens):
                resolved = {registry.get(token) for token in tokens}
                self.assertEqual(len(resolved), 1)
                self.assertIsNotNone(resolved.pop())

    def test_version_suffix_is_dropped(self):
        # A policy pinned to a version is the same policy.
        self.assertEqual(_normalise("internal_privacy_policy:v2"),
                         _normalise("internal privacy policy"))

    def test_criteria_are_found_at_either_nesting_level(self):
        self.assertEqual(criteria_from_intent({"criteria": ["gdpr"]}), ["gdpr"])
        self.assertEqual(
            criteria_from_intent({"assessment": {"criteria": ["nis2"]}}), ["nis2"]
        )

    def test_a_bare_string_criterion_is_accepted(self):
        self.assertEqual(criteria_from_intent({"criteria": "gdpr"}), ["gdpr"])

    def test_no_criteria_yields_no_compliance_claim(self):
        self.assertEqual(criteria_from_intent({}), [])
        self.assertEqual(coverage_for_intent({}, "mia-privacy"), {})


class CoverageStatusTest(unittest.TestCase):
    """The three outcomes, and the distinction that motivates them."""

    def test_criterion_with_an_evaluable_requirement_is_assessed(self):
        coverage, = resolve_coverage(["testreg"], "mia-privacy", _TEST_REGISTRY)
        self.assertEqual(coverage.status, "assessed")
        self.assertEqual(len(coverage.assessed_requirements), 1)

    def test_assessed_criterion_still_reports_what_it_did_not_cover(self):
        # The point of the whole module: "assessed" must not read as "fully
        # met". One of two requirements was evidenced, and the other is named.
        coverage, = resolve_coverage(["testreg"], "mia-privacy", _TEST_REGISTRY)
        self.assertEqual(len(coverage.unassessed_requirements), 1)
        self.assertIn("1 of 2", coverage.note)

    def test_known_source_no_evaluable_requirement_is_declared_not_assessed(self):
        coverage, = resolve_coverage(["unevaluable"], "mia-privacy", _TEST_REGISTRY)
        self.assertEqual(coverage.status, "declaredNotAssessed")
        self.assertEqual(coverage.assessed_requirements, [])
        self.assertIn("says nothing", coverage.note)

    def test_unknown_token_is_reported_not_dropped(self):
        coverage, = resolve_coverage(
            ["internal_privacy_policy:v2"], "mia-privacy", _TEST_REGISTRY
        )
        self.assertEqual(coverage.status, "unrecognised")
        self.assertEqual(coverage.criterion, "internal_privacy_policy:v2")
        self.assertIn("manual review", coverage.note)

    def test_a_different_skill_does_not_inherit_coverage(self):
        coverage, = resolve_coverage(["testreg"], "sast-python", _TEST_REGISTRY)
        self.assertEqual(coverage.status, "declaredNotAssessed")

    def test_unrecognised_token_counts_against_completeness(self):
        # Conservative on purpose: a reader cannot tell from the report whether
        # an unresolved criterion mattered.
        summary = coverage_summary(
            resolve_coverage(["testreg", "mystery"], "mia-privacy", _TEST_REGISTRY)
        )
        self.assertEqual(summary["byStatus"],
                         {"assessed": 1, "unrecognised": 1})
        self.assertFalse(summary["complete"])

    def test_complete_only_when_every_criterion_was_assessed(self):
        summary = coverage_summary(
            resolve_coverage(["testreg"], "mia-privacy", _TEST_REGISTRY)
        )
        self.assertTrue(summary["complete"])

    def test_failed_run_claims_no_coverage(self):
        # A run that produced no evidence must not report the obligations the
        # skill is merely capable of evidencing.
        summary = coverage_for_intent(
            {"criteria": ["testreg"]},
            "mia-privacy",
            registry=_TEST_REGISTRY,
            produced_evidence=False,
        )
        self.assertEqual(summary["byStatus"], {"declaredNotAssessed": 1})
        self.assertFalse(summary["complete"])

    def test_ontology_matches_the_intent_sample(self):
        # Integration check against the real ontology, using the criteria in
        # intents/sample_intent_mia.json-orig.
        summary = coverage_for_intent(
            {"criteria": ["gdpr", "internal_privacy_policy:v2"]}, "mia-privacy"
        )
        self.assertEqual(summary["byStatus"].get("assessed"), 1)
        self.assertEqual(summary["byStatus"].get("unrecognised"), 1)
        self.assertFalse(summary["complete"])
        gdpr, = [c for c in summary["criteria"] if c["status"] == "assessed"]
        self.assertTrue(gdpr["assessedRequirements"])
        self.assertTrue(gdpr["unassessedRequirements"])


class BandingTest(unittest.TestCase):
    """Reduced numbers must stay consistent with the exact ones."""

    def test_counts_band_monotonically(self):
        self.assertEqual(band_count(0), "none")
        self.assertEqual(band_count(2), "a few")
        self.assertEqual(band_count(7), "several")
        self.assertEqual(band_count(400), "many")

    def test_magnitude_is_described_relative_to_the_threshold(self):
        self.assertEqual(band_magnitude(0.01, 0.10), "well within the threshold")
        self.assertEqual(band_magnitude(0.08, 0.10), "approaching the threshold")
        self.assertEqual(band_magnitude(0.11, 0.10),
                         "at or just above the threshold")
        self.assertEqual(band_magnitude(0.30, 0.10),
                         "substantially above the threshold")

    def test_a_crossed_threshold_never_bands_as_within_it(self):
        # The banding is only defensible if it cannot contradict the verdict.
        for value in (0.10, 0.1357, 0.5, 1.0):
            self.assertNotIn("within", band_magnitude(value, 0.10))

    def test_sign_does_not_hide_magnitude(self):
        # A negative advantage is still an advantage of that size.
        self.assertEqual(band_magnitude(-0.30, 0.10),
                         band_magnitude(0.30, 0.10))

    def test_missing_threshold_is_stated_not_guessed(self):
        self.assertEqual(band_magnitude(0.5, None),
                         "not comparable to a threshold")
        self.assertEqual(band_magnitude(0.5, 0), "not comparable to a threshold")


class ProfileResolutionTest(unittest.TestCase):
    """How an audience is chosen, and what that choice cannot do."""

    def test_the_four_named_audiences_are_reachable_by_role(self):
        for role, expected in (
            ("SecurityAuditor", "technical"),
            ("Developer", "technical"),
            ("CISO", "management"),
            ("ComplianceOfficer", "compliance"),
            ("Sales", "external"),
        ):
            with self.subTest(role=role):
                profile, why = resolve_profile({"actor": {"role": role}})
                self.assertEqual(profile.name, expected)
                self.assertIn(role, why)

    def test_role_matching_is_case_insensitive(self):
        profile, _ = resolve_profile({"actor": {"role": "ciso"}})
        self.assertEqual(profile.name, "management")

    def test_explicit_request_wins_over_the_asserted_role(self):
        profile, why = resolve_profile(
            {"actor": {"role": "CISO"}}, requested="technical"
        )
        self.assertEqual(profile.name, "technical")
        self.assertIn("requested", why)

    def test_unknown_role_falls_back_to_the_default(self):
        profile, why = resolve_profile({"actor": {"role": "Chief Vibes Officer"}})
        self.assertEqual(profile.name, "technical")
        self.assertEqual(why, "default")

    def test_resolution_reason_is_always_recorded(self):
        # A reader asking why their report lost the matrix needs this field.
        for intent in ({}, {"actor": {"role": "CISO"}},
                       {"reporting": {"profile": "compliance"}}):
            _, why = resolve_profile(intent)
            self.assertTrue(why)

    def test_asserted_role_cannot_widen_disclosure(self):
        # audience is self-asserted; disclosureClass is server-enforced. The
        # effective class is the more restrictive of the two.
        internal = REGISTRY.get("technical")
        self.assertEqual(
            effective_disclosure(internal, permitted="external"), "external"
        )
        self.assertEqual(
            effective_disclosure(internal, permitted="internal"), "internal"
        )

    def test_unknown_permission_fails_closed(self):
        internal = REGISTRY.get("technical")
        self.assertEqual(
            effective_disclosure(internal, permitted="nonsense"), "external"
        )

    def test_shipped_sample_intents_resolve_to_a_profile(self):
        # The samples in intents/ declare their role under ``actor.role``; this
        # catches a profile change that stops covering the roles actually in use.
        import json

        samples = sorted(
            (Path(__file__).resolve().parent.parent / "intents").glob(
                "sample_intent_*.json"
            )
        )
        self.assertTrue(samples)
        for sample in samples:
            with self.subTest(intent=sample.name):
                intent = json.loads(sample.read_text())
                profile, why = resolve_profile(intent)
                self.assertIn(profile.name, REGISTRY.names())
                self.assertTrue(why)
                if profile.disclosure_class == "external":
                    # External is reachable only on purpose. An intent that
                    # lands there by role alone would be a mistake: the path is
                    # gated and releases almost nothing, so a sample must have
                    # asked for it explicitly.
                    self.assertEqual(
                        (intent.get("reporting") or {}).get("profile"),
                        profile.name,
                        f"{sample.name} resolved to the external profile "
                        "without declaring reporting.profile",
                    )

    def test_a_sample_intent_exists_for_every_profile(self):
        # The four profiles are the feature's user-facing surface; each needs a
        # runnable example, or the audiences are only documented in code.
        import json

        resolved = set()
        for sample in (Path(__file__).resolve().parent.parent / "intents").glob(
            "sample_intent_*.json"
        ):
            profile, _ = resolve_profile(json.loads(sample.read_text()))
            resolved.add(profile.name)
        self.assertEqual(resolved, set(REGISTRY.names()))


class ProjectionAgreementTest(unittest.TestCase):
    """Every rendition of one assessment must tell the same story."""

    @classmethod
    def setUpClass(cls):
        intent = {
            "intentId": "intent-test",
            "criteria": ["gdpr", "internal_privacy_policy:v2"],
        }
        cls.facts = normalize(
            {"status": "success", "data": OBSERVED_SWEEP}, intent=intent
        ).to_dict()
        cls.renditions = project_all(
            cls.facts,
            resolved_by="test",
            regulatory_mapping=cls.facts["regulatoryCoverage"],
            provenance={"agent": "test-agent"},
        )
        cls.internal = {
            name: rendition
            for name, rendition in cls.renditions.items()
            if name != "external"
        }

    def test_every_internal_rendition_carries_the_same_verdict(self):
        for name, rendition in self.internal.items():
            with self.subTest(profile=name):
                self.assertEqual(rendition["verdict"]["worstSeverity"], "HIGH")

    def test_no_rendition_softens_the_high_severity_result(self):
        # The defect this work fixes: the stored narratives called this data
        # "high resilience". No projection may reintroduce that reading.
        for name, rendition in self.internal.items():
            with self.subTest(profile=name):
                titles = " ".join(
                    finding["title"] for finding in rendition["findings"]
                )
                self.assertIn("HIGH", [f["severity"] for f in rendition["findings"]])
                self.assertIn("0.135", titles)

    def test_the_worst_case_survives_the_management_reduction(self):
        # An executive summary of a sweep must be the worst case, not the
        # median — the median here is 12x smaller and would read as safe.
        headline = self.renditions["management"]["summaryFacts"]["headlineMetric"]
        self.assertAlmostEqual(headline["worstValue"], 0.1357, places=3)
        self.assertEqual(headline["worstConfiguration"]["batch_size"], 32)
        self.assertNotEqual(headline["worstValue"], headline["medianValue"])

    def test_the_headline_metric_is_never_the_derived_one(self):
        # score is (1 - |adv|)/2 and moves inversely; as a headline it would
        # read as 0.43-out-of-1 rather than as an advantage of 0.136.
        for name, rendition in self.internal.items():
            with self.subTest(profile=name):
                headline = rendition["summaryFacts"].get("headlineMetric")
                if headline:
                    self.assertEqual(
                        headline["metric"], "membershipInferenceAdvantage"
                    )

    def test_observation_count_excludes_derived_restatements(self):
        # 13 sweep rows, two metric columns: the evidence is 13 measurements,
        # not 26.
        self.assertEqual(
            self.renditions["technical"]["summaryFacts"]["observationCount"], 13
        )

    def test_scope_limitations_are_never_truncated(self):
        canonical = self.facts["scopeLimitations"]
        self.assertTrue(canonical)
        for name, rendition in self.internal.items():
            with self.subTest(profile=name):
                self.assertEqual(rendition["scopeLimitations"], canonical)

    def test_renditions_are_reconcilable_against_the_canonical_facts(self):
        for name, rendition in self.internal.items():
            with self.subTest(profile=name):
                marker = rendition["reportProfile"]
                self.assertEqual(marker["canonicalWorstSeverity"], "HIGH")
                self.assertEqual(
                    marker["canonicalFindingCount"], len(self.facts["findings"])
                )

    def test_projection_is_deterministic(self):
        again = project_all(
            self.facts,
            resolved_by="test",
            regulatory_mapping=self.facts["regulatoryCoverage"],
            provenance={"agent": "test-agent"},
        )
        self.assertEqual(again, self.renditions)


class SectionSelectionTest(unittest.TestCase):
    """Audiences are not one detail ladder; they select sections."""

    @classmethod
    def setUpClass(cls):
        cls.facts = normalize(
            {"status": "success", "data": OBSERVED_SWEEP},
            intent={"criteria": ["gdpr"]},
        ).to_dict()
        cls.renditions = project_all(
            cls.facts,
            regulatory_mapping=cls.facts["regulatoryCoverage"],
            provenance={"agent": "test-agent"},
        )

    def test_audiences_are_not_orderable_by_detail(self):
        # This is why detailLevel was rejected as a scalar: compliance takes a
        # section the technical profile omits, and vice versa.
        technical = set(self.renditions["technical"])
        compliance = set(self.renditions["compliance"])
        self.assertIn("regulatoryMapping", compliance - technical)
        self.assertIn("evidence",
                      set(self.renditions["technical"]["findings"][0]))
        self.assertNotIn("evidence",
                         set(self.renditions["compliance"]["findings"][0]))

    def test_only_the_technical_profile_gets_per_finding_evidence(self):
        for name in ("management", "compliance"):
            with self.subTest(profile=name):
                for finding in self.renditions[name]["findings"]:
                    self.assertNotIn("evidence", finding)
                    self.assertNotIn("technicalDetail", finding)

    def test_management_keeps_the_consequence_without_the_mechanism(self):
        finding = self.renditions["management"]["findings"][0]
        self.assertTrue(finding["businessImpact"])
        self.assertNotIn("technicalDetail", finding)
        # A one-line remediation is a decision input; the steps are not.
        self.assertEqual(list(finding["remediation"]), ["oneLine"])

    def test_compliance_gets_method_and_thresholds(self):
        method = self.renditions["compliance"]["method"]
        self.assertEqual(method["thresholdSource"],
                         "docs/skills/ontology/intrust.ttl")
        self.assertEqual(method["rowCount"], 13)

    def test_management_is_not_shown_the_full_matrix(self):
        self.assertNotIn("observations", self.renditions["management"])

    def test_raw_result_is_withheld_unless_a_profile_asks_for_it(self):
        for name, rendition in self.renditions.items():
            with self.subTest(profile=name):
                self.assertNotIn("rawResult", rendition)


class SweepReductionTest(unittest.TestCase):
    """A sweep is reduced by aggregation, and the reduction is declared."""

    @classmethod
    def setUpClass(cls):
        cls.facts = normalize(
            {"status": "success", "data": OBSERVED_SWEEP}
        ).to_dict()

    def _rendition(self, profile_name):
        return project(self.facts, REGISTRY.get(profile_name))

    def test_technical_profile_keeps_every_observation(self):
        rendition = self._rendition("technical")
        self.assertEqual(len(rendition["observations"]),
                         len(self.facts["observations"]))
        self.assertEqual(rendition["observationReduction"]["omitted"], 0)

    def test_per_dimension_reduction_keeps_the_worst_of_each_value(self):
        rendition = self._rendition("compliance")
        reduction = rendition["observationReduction"]
        self.assertEqual(reduction["projection"], "perDimension")
        self.assertLess(reduction["kept"], reduction["total"])
        # The worst cell must survive: it is what shows where risk concentrates.
        advantages = [
            observation["value"]
            for observation in rendition["observations"]
            if observation["metric"] == "membershipInferenceAdvantage"
        ]
        self.assertAlmostEqual(max(advantages), 0.1357, places=3)

    def test_every_reduction_declares_what_it_dropped(self):
        for name in ("technical", "compliance"):
            with self.subTest(profile=name):
                reduction = self._rendition(name)["observationReduction"]
                self.assertEqual(
                    reduction["kept"] + reduction["omitted"], reduction["total"]
                )

    def test_findings_omitted_is_reported_when_a_floor_applies(self):
        # The management floor is MEDIUM and the fixture has a LOW finding.
        marker = self._rendition("management")["reportProfile"]
        self.assertEqual(marker["severityFloor"], "MEDIUM")
        self.assertGreater(marker["findingsOmitted"], 0)


#: An assessment date and a recorded approval, as the API supplies them.  Both
#: are required for release, so tests that exercise the released payload have to
#: pass them; tests of the gates themselves leave one out deliberately.
ASSESSED_ON = "2026-08-06T10:00:00+00:00"
APPROVAL = {
    "state": "approved",
    "approvedBy": "release-board",
    "recordedAt": "2026-08-06T12:00:00+00:00",
    "reference": "CR-1234",
}


class ExternalGateTest(unittest.TestCase):
    """The external artifact is allowlisted and gated, not merely shortened."""

    def setUp(self):
        self.profile = REGISTRY.get("external")

    def _facts(self, sweep, status="success"):
        return normalize({"status": status, "data": sweep}).to_dict()

    def _released(self, facts, **overrides):
        """Project with every release condition met unless a test removes one."""
        kwargs = {"assessed_on": ASSESSED_ON, "approval": APPROVAL}
        kwargs.update(overrides)
        return project(facts, self.profile, **kwargs)

    def test_no_artifact_is_produced_for_a_high_severity_assessment(self):
        rendition = project(self._facts(OBSERVED_SWEEP), self.profile)
        self.assertFalse(rendition["released"])
        self.assertTrue(rendition["withheldBecause"])

    def test_withholding_says_why(self):
        rendition = project(self._facts(OBSERVED_SWEEP), self.profile)
        self.assertIn("HIGH", " ".join(rendition["withheldBecause"]))

    def test_a_withheld_artifact_leaks_no_measurements(self):
        # The failure mode worth guarding: a gate that still emits the figures.
        rendition = project(self._facts(OBSERVED_SWEEP), self.profile)
        serialised = repr(rendition)
        for leak in ("0.135", "batch_size", "adam", "model_id", "cd7"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, serialised)

    def test_a_clean_assessment_releases_an_allowlisted_statement(self):
        clean = (
            "model_id;optim;lr;batch_size;train_acc;test_acc;adv;score\n"
            "aaa;adam;0.5;64;0.98;0.95;0.001;0.4995\n"
            "bbb;sgd;0.5;64;0.97;0.94;0.002;0.499\n"
        )
        rendition = self._released(self._facts(clean))
        self.assertTrue(rendition["released"])
        self.assertEqual(rendition["verdict"], "pass")
        payload = {
            key: value
            for key, value in rendition.items()
            if key not in ("released", "reportProfile")
        }
        self.assertTrue(set(payload) <= set(EXTERNAL_ALLOWLIST))

    def test_a_released_statement_carries_no_figures_or_identifiers(self):
        clean = (
            "model_id;optim;lr;batch_size;train_acc;test_acc;adv;score\n"
            "aaa;adam;0.5;64;0.98;0.95;0.001;0.4995\n"
        )
        rendition = self._released(self._facts(clean))
        serialised = repr(rendition)
        for leak in ("0.001", "aaa", "batch_size", "0.4995"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, serialised)

    def test_a_failed_assessment_is_not_released_as_a_pass(self):
        facts = normalize({"status": "error", "message": "MIA service unreachable"})
        rendition = project(facts.to_dict(), self.profile)
        self.assertFalse(rendition["released"])
        self.assertIn("FAILED", " ".join(rendition["withheldBecause"]))

    def test_an_inconclusive_assessment_is_not_released_as_a_pass(self):
        facts = normalize({"status": "success", "data": ""})
        rendition = project(facts.to_dict(), self.profile)
        self.assertFalse(rendition["released"])

    def test_the_external_path_cannot_be_bypassed(self):
        # project() routes on disclosure class, so an external profile can
        # never reach the internal projector by calling the general entry point.
        rendition = project(self._facts(OBSERVED_SWEEP), self.profile)
        self.assertNotIn("observations", rendition)
        self.assertNotIn("findings", rendition)

    def test_external_disclosure_belongs_to_exactly_one_profile(self):
        external = [p for p in PROFILES if p.disclosure_class == "external"]
        self.assertEqual([p.name for p in external], ["external"])

    def test_the_external_profile_declares_no_reduction(self):
        # It carries neither findings nor observations, so a floor or a sweep
        # projection would describe a reduction that never happens.
        self.assertIsNone(self.profile.severity_floor)
        self.assertIsNone(self.profile.sweep_projection)

    def test_a_low_severity_result_withholds_the_statement(self):
        # Any finding at all blocks release, not only one at a floor: with
        # every other gate met, a LOW worst case is still withheld.
        clean = (
            "model_id;optim;lr;batch_size;train_acc;test_acc;adv;score\n"
            "aaa;adam;0.5;64;0.98;0.95;0.001;0.4995\n"
        )
        facts = self._facts(clean)
        self.assertTrue(self._released(facts)["released"])
        facts["worstSeverity"] = "LOW"
        rendition = self._released(facts)
        self.assertFalse(rendition["released"])
        self.assertIn("LOW", " ".join(rendition["withheldBecause"]))


class SweepProjectionFailsClosedTest(unittest.TestCase):
    """An unrecognised sweep projection must not show the full sweep."""

    def test_an_unknown_projection_raises(self):
        profile = dataclasses.replace(
            REGISTRY.get("compliance"), sweep_projection="argmaks"
        )
        facts = normalize({"status": "success", "data": OBSERVED_SWEEP}).to_dict()
        with self.assertRaises(ValueError):
            project(facts, profile)


class ExternalApprovalGateTest(unittest.TestCase):
    """
    ``requiresApprovalBeforeRelease`` must name a condition that was checked.

    Before this gate the flag was set on every released statement while nothing
    consumed it, which is worse than having no field: it reads as a control.
    """

    def setUp(self):
        self.profile = REGISTRY.get("external")
        self.facts = normalize(
            {
                "status": "success",
                "data": (
                    "model_id;optim;lr;batch_size;train_acc;test_acc;adv;score\n"
                    "aaa;adam;0.5;64;0.98;0.95;0.001;0.4995\n"
                ),
            }
        ).to_dict()

    def _project(self, **kwargs):
        return project(self.facts, self.profile, **kwargs)

    def test_a_clean_assessment_is_withheld_until_someone_approves(self):
        rendition = self._project(assessed_on=ASSESSED_ON)
        self.assertFalse(rendition["released"])
        self.assertIn("approved", " ".join(rendition["withheldBecause"]))

    def test_the_default_is_unapproved_rather_than_approved(self):
        # A caller that knows nothing about approval must withhold.  The
        # opposite default would release on every path that had not been
        # updated to pass an approval.
        self.assertFalse(self._project(assessed_on=ASSESSED_ON)["released"])

    def test_an_approval_without_a_named_approver_does_not_release(self):
        # An approval nobody is attached to cannot be questioned afterwards.
        rendition = self._project(
            assessed_on=ASSESSED_ON, approval={"state": "approved"}
        )
        self.assertFalse(rendition["released"])

    def test_a_pending_approval_does_not_release(self):
        rendition = self._project(
            assessed_on=ASSESSED_ON,
            approval={"state": "pending", "approvedBy": "release-board"},
        )
        self.assertFalse(rendition["released"])

    def test_an_approval_releases_and_records_who_gave_it(self):
        marker = self._project(assessed_on=ASSESSED_ON, approval=APPROVAL)[
            "reportProfile"
        ]
        self.assertEqual(marker["approvalState"], "approved")
        self.assertEqual(marker["approvedBy"], "release-board")
        self.assertEqual(marker["approvalReference"], "CR-1234")

    def test_the_requirement_is_stated_on_a_withheld_statement_too(self):
        # The requirement is a property of the profile, not of the outcome; a
        # reader asking why nothing was released should see approval among the
        # conditions rather than infer it from its absence.
        marker = self._project(assessed_on=ASSESSED_ON)["reportProfile"]
        self.assertTrue(marker["requiresApprovalBeforeRelease"])
        self.assertEqual(marker["approvalState"], "pending")

    def test_approval_does_not_override_the_other_gates(self):
        # The failure mode worth guarding: approval read as a release switch.
        adverse = normalize(
            {"status": "success", "data": OBSERVED_SWEEP}
        ).to_dict()
        rendition = project(
            adverse, self.profile, assessed_on=ASSESSED_ON, approval=APPROVAL
        )
        self.assertFalse(rendition["released"])
        self.assertIn("HIGH", " ".join(rendition["withheldBecause"]))

    def test_every_gate_is_advertised(self):
        rendition = self._project()
        self.assertEqual(
            rendition["reportProfile"]["gates"], list(EXTERNAL_GATES)
        )
        self.assertIn("releaseMustBeApproved", EXTERNAL_GATES)
        self.assertIn("assessmentMustBeDated", EXTERNAL_GATES)


class ExternalValidityTest(unittest.TestCase):
    """
    A released statement is dated and expires.

    The claim describes a component at one moment; the component then changes
    and the artifact does not, so without an expiry it goes on reading as
    current indefinitely.
    """

    def setUp(self):
        self.profile = REGISTRY.get("external")
        self.facts = normalize(
            {
                "status": "success",
                "data": (
                    "model_id;optim;lr;batch_size;train_acc;test_acc;adv;score\n"
                    "aaa;adam;0.5;64;0.98;0.95;0.001;0.4995\n"
                ),
            }
        ).to_dict()

    def _project(self, **kwargs):
        return project(self.facts, self.profile, **kwargs)

    def test_an_undated_assessment_is_not_released(self):
        rendition = self._project(approval=APPROVAL)
        self.assertFalse(rendition["released"])
        self.assertIn("expiry", " ".join(rendition["withheldBecause"]))

    def test_an_unparseable_date_is_not_released(self):
        # Withheld rather than released with a missing expiry: a statement that
        # cannot expire is the thing this gate exists to prevent.
        rendition = self._project(assessed_on="last Tuesday", approval=APPROVAL)
        self.assertFalse(rendition["released"])

    def test_a_released_statement_states_both_dates(self):
        rendition = self._project(assessed_on=ASSESSED_ON, approval=APPROVAL)
        self.assertTrue(rendition["released"])
        self.assertEqual(rendition["assessedOn"], ASSESSED_ON)
        self.assertTrue(rendition["validUntil"])

    def test_the_expiry_is_later_than_the_assessment(self):
        rendition = self._project(assessed_on=ASSESSED_ON, approval=APPROVAL)
        self.assertGreater(rendition["validUntil"], rendition["assessedOn"])

    def test_the_expiry_is_the_configured_period_after_the_assessment(self):
        from datetime import datetime, timedelta

        rendition = self._project(assessed_on=ASSESSED_ON, approval=APPROVAL)
        expected = datetime.fromisoformat(ASSESSED_ON) + timedelta(
            days=EXTERNAL_VALIDITY_DAYS
        )
        self.assertEqual(
            datetime.fromisoformat(rendition["validUntil"]), expected
        )

    def test_the_rule_behind_the_expiry_is_stated_not_just_the_date(self):
        marker = self._project(assessed_on=ASSESSED_ON, approval=APPROVAL)[
            "reportProfile"
        ]
        self.assertEqual(marker["validityPeriod"], EXTERNAL_VALIDITY_PERIOD)

    def test_a_trailing_z_timestamp_is_accepted(self):
        # What ``datetime.isoformat()`` produces varies by source; a UTC "Z"
        # must not be read as an unparseable date and silently withhold.
        rendition = self._project(
            assessed_on="2026-08-06T10:00:00Z", approval=APPROVAL
        )
        self.assertTrue(rendition["released"])

    def test_the_statement_says_it_expires(self):
        # The dates are useless to a reader who is not told they bound the
        # claim, and an external reader sees only the prose.
        rendition = self._project(assessed_on=ASSESSED_ON, approval=APPROVAL)
        self.assertIn("re-established", rendition["statement"])

    def test_the_dates_are_allowlisted(self):
        for field in ("assessedOn", "validUntil"):
            with self.subTest(field=field):
                self.assertIn(field, EXTERNAL_ALLOWLIST)

    def test_projection_with_dates_is_still_deterministic(self):
        # The reason the date is injected rather than read from the clock here:
        # a rendition is re-projected on every read, and an expiry that moved
        # between two reads of one assessment would be worthless.
        first = self._project(assessed_on=ASSESSED_ON, approval=APPROVAL)
        second = self._project(assessed_on=ASSESSED_ON, approval=APPROVAL)
        self.assertEqual(first, second)

    def test_internal_profiles_are_not_gated_on_either_condition(self):
        # An internal reader needs the result whether or not anyone has cleared
        # it for release.
        for name in ("technical", "management", "compliance"):
            with self.subTest(profile=name):
                rendition = project(self.facts, REGISTRY.get(name))
                self.assertIn("verdict", rendition)


class DegradedFactsTest(unittest.TestCase):
    """Projection must survive results that carry no findings at all."""

    def test_a_failed_assessment_projects_without_raising(self):
        facts = normalize({"status": "error", "message": "MIA service unreachable"})
        for profile in PROFILES:
            with self.subTest(profile=profile.name):
                rendition = project(facts.to_dict(), profile)
                self.assertIsInstance(rendition, dict)

    def test_a_failed_assessment_reports_no_severity_as_none(self):
        facts = normalize({"status": "error", "message": "MIA service unreachable"})
        rendition = project(facts.to_dict(), REGISTRY.get("technical"))
        self.assertEqual(rendition["verdict"]["status"], "FAILED")
        self.assertEqual(rendition["verdict"]["worstSeverity"], "NONE")

    def test_an_empty_fact_model_projects_empty_sections(self):
        rendition = project(
            {"status": "INCONCLUSIVE", "worstSeverity": "NONE"},
            REGISTRY.get("compliance"),
        )
        self.assertEqual(rendition["findings"], [])
        self.assertEqual(rendition["scopeLimitations"], [])

    def test_absent_regulatory_mapping_omits_the_section(self):
        facts = normalize({"status": "success", "data": OBSERVED_SWEEP}).to_dict()
        rendition = project(facts, REGISTRY.get("compliance"))
        self.assertNotIn("regulatoryMapping", rendition)


class ProvenanceBackfillTest(unittest.TestCase):
    """
    The fields the framework knows are not left to the composing model.

    ``provenance`` is a scaffold the model fills in, and where the scaffold names
    a property it cannot know, it invents a plausible value — the same failure
    that produced the same 2023 timestamp in every report.  ``toolVersion`` is
    the other instance: a version in a report is a claim about which build
    produced the evidence, and a reader cannot tell an invented one from a real
    one.
    """

    _SPA = "https://intend-project.eu/ontology/spa#"
    _STAMP = "2026-08-11T10:00:00+00:00"

    def _backfill(self, composed, result):
        from orchestrator.agent import RuntimeOrchestrator

        return RuntimeOrchestrator._backfill_required_fields(
            composed,
            {"intentId": "intent-1"},
            None,
            result,
            self._STAMP,
        )

    def test_a_reported_version_replaces_whatever_the_model_wrote(self):
        composed = self._backfill(
            {"provenance": {"toolVersion": "MIA service v2.4.1"}},
            {"status": "success", "version": "0.0.9"},
        )
        self.assertEqual(composed["provenance"]["toolVersion"], "0.0.9")

    def test_an_invented_version_is_removed_when_the_tool_reports_none(self):
        # The core guard: with no version in the envelope the field must not
        # survive, or the fabrication passes straight through.
        composed = self._backfill(
            {"provenance": {"toolVersion": "MIA service v2.4.1"}},
            {"status": "success"},
        )
        self.assertNotIn("toolVersion", composed["provenance"])
        # The timestamp is still stamped: removing one field must not skip the
        # rest of the backfill.
        self.assertEqual(
            composed["provenance"]["executionTimestamp"], self._STAMP
        )

    def test_the_expanded_ontology_spelling_is_corrected_too(self):
        # The model writes provenance under either the bare name or the IRI, and
        # a fabrication under the spelling we did not check would survive.
        key = f"{self._SPA}provenance"
        composed = self._backfill(
            {key: {"toolVersion": "MIA service v2.4.1"}},
            {"status": "success"},
        )
        self.assertNotIn("toolVersion", composed[key])

    def test_a_missing_provenance_block_gains_the_version(self):
        composed = self._backfill(
            {}, {"status": "success", "version": "0.0.9"}
        )
        self.assertEqual(composed["provenance"]["toolVersion"], "0.0.9")
        self.assertEqual(
            composed["provenance"]["executionTimestamp"], self._STAMP
        )

    def test_a_missing_provenance_block_invents_no_version(self):
        composed = self._backfill({}, {"status": "success"})
        self.assertNotIn("toolVersion", composed["provenance"])

    def test_other_provenance_fields_are_left_alone(self):
        # Only the fields the framework owns are overwritten; the model's own
        # contributions are not collateral.
        composed = self._backfill(
            {"provenance": {"toolVersion": "invented", "tool": "MIA service"}},
            {"status": "success"},
        )
        self.assertEqual(composed["provenance"]["tool"], "MIA service")


if __name__ == "__main__":
    unittest.main(verbosity=2)
