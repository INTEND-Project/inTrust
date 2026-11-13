# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Tests for the MIA membership-inference normaliser and the ontology
threshold registry.

Run with the stdlib runner (no pytest dependency required)::

    python -m unittest discover -s tests -v

The sweep table in ``OBSERVED_SWEEP`` is the verbatim payload the MIA service returned
in ``logs/intrust.log`` — it is the regression fixture for the misreport this
work fixes: three stored agent summaries described this data as showing "high
resilience" and "no significant leakage", when two configurations exceed the
high-risk advantage threshold.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.fact_model import severity_rank  # noqa: E402
from orchestrator.threshold_registry import load_registry  # noqa: E402
from tools.mia_normalizer import normalize, parse_sweep_table  # noqa: E402

OBSERVED_SWEEP = (
    "model_id;optim;lr;batch_size;train_acc;test_acc;adv;score\n"
    "821...ae1;adam;0.5;64;1.0;1.0;-0.0032000000000000084;0.4984\n"
    "df1...35b;sgd;0.1;128;1.0;1.0;0.007700000000000012;0.49615\n"
    "032...68e;adam;0.1;128;1.0;1.0;0.008000000000000007;0.496\n"
    "d1d...eb6;adam;0.5;128;1.0;1.0;0.008800000000000002;0.4956\n"
    "a7f...640;sgd;0.5;128;1.0;1.0;0.01100000000000001;0.4945\n"
    "2f7...e1f;sgd;0.1;64;1.0;1.0;0.011099999999999999;0.49445\n"
    "871...5b8;adam;0.5;128;1.0;1.0;0.012800000000000006;0.4936\n"
    "492...b44;adam;0.1;64;1.0;1.0;0.013399999999999995;0.4933\n"
    "10d...c4f;sgd;0.5;64;1.0;1.0;-0.022199999999999998;0.4889\n"
    "844...999;sgd;0.5;32;1.0;1.0;-0.023800000000000043;0.4881\n"
    "39b...4d7;adam;0.5;32;1.0;1.0;-0.03200000000000003;0.484\n"
    "cd7...7dc;sgd;0.1;32;1.0;1.0;0.11939999999999995;0.4403\n"
    "305...03e;adam;0.1;32;1.0;1.0;0.13569999999999993;0.43215000000000003\n"
)

ADVANTAGE = "membershipInferenceAdvantage"
SCORE = "membershipInferenceScore"


def _advantages(facts):
    return [o for o in facts.observations if o.metric == ADVANTAGE]


def _summary(facts, metric):
    return next(m for m in facts.metric_summaries if m.metric == metric)


class ThresholdRegistryTest(unittest.TestCase):
    """The ontology is the source of truth for severity boundaries."""

    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry()

    def test_advantage_metric_is_declared(self):
        definition = self.registry.get(ADVANTAGE)
        self.assertIsNotNone(definition)
        self.assertTrue(definition.higher_is_worse)
        self.assertEqual(len(definition.thresholds), 3)

    def test_classification_picks_most_severe_matching_band(self):
        definition = self.registry.get(ADVANTAGE)
        self.assertEqual(definition.classify(0.1357)[0], "HIGH")
        self.assertEqual(definition.classify(0.07)[0], "MEDIUM")
        self.assertEqual(definition.classify(0.03)[0], "LOW")
        self.assertEqual(definition.classify(0.008)[0], "NONE")

    def test_classification_uses_magnitude_for_upper_bounded_metric(self):
        # Sign records the direction of the adversary's bias; a negative
        # advantage of the same magnitude is the same size of leak.
        definition = self.registry.get(ADVANTAGE)
        self.assertEqual(definition.classify(-0.1357)[0], "HIGH")
        self.assertEqual(definition.classify(-0.032)[0], "LOW")

    def test_classification_cites_the_threshold_individual(self):
        _, iri = self.registry.get(ADVANTAGE).classify(0.1357)
        self.assertIsNotNone(iri)
        self.assertTrue(iri.endswith("MIAAdvantageHighThreshold"))

    def test_score_metric_records_inverse_polarity_and_derivation(self):
        definition = self.registry.get(SCORE)
        self.assertIsNotNone(definition)
        # Lower score is worse — the trap that produced the original misreport.
        self.assertFalse(definition.higher_is_worse)
        self.assertEqual(definition.derived_from, ADVANTAGE)
        self.assertEqual(definition.thresholds, ())

    def test_the_mia_thresholds_are_confirmed(self):
        # Confirmed with the team that owns the MIA attack implementation, so
        # the boundaries no longer carry the provisional flag.  The values are
        # unchanged by the confirmation: what changed is that they can be relied
        # on, which is why this asserts both.
        definition = self.registry.get(ADVANTAGE)
        self.assertEqual(definition.provisional_thresholds(), ())
        self.assertEqual(
            sorted(t.value for t in definition.thresholds), [0.02, 0.05, 0.10]
        )

    def test_provisional_status_is_read_from_the_ontology_property(self):
        # Not from the rdfs:comment prose: the flag has to be machine-readable
        # for a normalizer to carry it into a report.  Exercised against a
        # constructed threshold rather than the MIA ones, since those are now
        # confirmed — the mechanism has to keep working for the next metric
        # whose boundaries are not.
        from orchestrator.threshold_registry import MetricDefinition, Threshold

        definition = MetricDefinition(
            identifier="m", iri="urn:m", label=None, unit=None,
            definition_text=None, higher_is_worse=True,
            aggregation_function=None,
            thresholds=(
                Threshold(
                    iri="urn:t", local_name="t", value=1.0,
                    operator="greater-than", severity="HIGH",
                    provisional=True, provisional_reason="pending review",
                ),
                Threshold(
                    iri="urn:u", local_name="u", value=0.5,
                    operator="greater-than", severity="LOW",
                ),
            ),
        )
        self.assertEqual(len(definition.provisional_thresholds()), 1)
        self.assertEqual(definition.provisional_thresholds()[0].local_name, "t")

    def test_every_provisional_threshold_in_the_ontology_says_what_is_outstanding(self):
        # A bare flag tells a reader the severity is unconfirmed without
        # telling them what would confirm it.  ThresholdShape enforces this in
        # the ontology; this asserts the reason survives the load, for whichever
        # thresholds carry the flag — vacuously true now that the MIA service's are
        # confirmed, and the guard that matters when the next one is added.
        for definition in self.registry.list():
            for threshold in definition.provisional_thresholds():
                with self.subTest(threshold=threshold.local_name):
                    self.assertTrue(threshold.provisional_reason)

    def test_absent_property_means_confirmed_not_provisional(self):
        # A missing flag must not mark a settled boundary as doubtful, or every
        # threshold in the ontology acquires a caveat by default.
        from orchestrator.threshold_registry import Threshold

        plain = Threshold(
            iri="urn:t", local_name="t", value=1.0,
            operator="greater-than", severity="HIGH",
        )
        self.assertFalse(plain.provisional)

    def test_metric_semantics_provisional_is_separate_from_the_thresholds(self):
        # The MIA boundaries are confirmed; the sign of the ``adv`` column is
        # not.  Recorded on the metric definition rather than on a threshold,
        # because it qualifies the value before any boundary is applied and so
        # survives the confirmation of all three.
        definition = self.registry.get(ADVANTAGE)
        self.assertTrue(definition.semantics_provisional)
        self.assertTrue(definition.semantics_provisional_reason)
        self.assertEqual(definition.provisional_thresholds(), ())

    def test_metric_semantics_reason_names_the_reading_that_was_applied(self):
        # The reason text is carried into reports verbatim, and a reader cannot
        # weigh a finding on a negative advantage without knowing which reading
        # produced it and which way an error would run.
        reason = self.registry.get(ADVANTAGE).semantics_provisional_reason
        self.assertIn("absolute value", reason)
        self.assertIn("conservative", reason)

    def test_absent_semantics_property_means_confirmed(self):
        # Same default as for a threshold: an interpretation is only open if
        # someone says so.
        self.assertFalse(self.registry.get(SCORE).semantics_provisional)


class SweepParsingTest(unittest.TestCase):
    def test_parses_every_observed_row(self):
        rows, problems = parse_sweep_table(OBSERVED_SWEEP)
        self.assertEqual(len(rows), 13)
        self.assertEqual(problems, [])
        self.assertIsInstance(rows[0]["lr"], float)
        self.assertIsInstance(rows[0]["batch_size"], int)
        self.assertIsInstance(rows[0]["optim"], str)

    def test_malformed_row_is_reported_not_raised(self):
        rows, problems = parse_sweep_table(
            "model_id;adv\nabc;0.1\ntruncated\ndef;0.2\n"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(problems), 1)
        self.assertIn("row 3", problems[0])


class ObservedSweepTest(unittest.TestCase):
    """Regression tests against the payload that was previously misreported."""

    @classmethod
    def setUpClass(cls):
        cls.facts = normalize({"status": "success", "data": OBSERVED_SWEEP})

    def test_verdict_is_high_not_resilient(self):
        # The stored narratives concluded "high resilience". Two of thirteen
        # configurations exceed the 0.10 advantage threshold.
        self.assertEqual(self.facts.worst_severity, "HIGH")
        self.assertEqual(self.facts.status, "SUCCESS")

    def test_worst_case_is_reported_not_the_median(self):
        summary = _summary(self.facts, ADVANTAGE)
        self.assertAlmostEqual(summary.worst_value, 0.1357, places=4)
        self.assertAlmostEqual(summary.median_value, 0.0088, places=4)
        self.assertEqual(
            summary.worst_dimensions,
            {"optim": "adam", "lr": 0.1, "batch_size": 32},
        )

    def test_high_severity_finding_names_both_affected_configurations(self):
        high = [f for f in self.facts.findings if f.severity == "HIGH"]
        self.assertEqual(len(high), 1)
        detail = high[0].technical_detail
        self.assertEqual(detail["observationCount"], 2)
        self.assertEqual(detail["thresholdValue"], 0.10)
        # Both high-advantage cells sit at lr=0.1, batch_size=32 — the
        # interaction is the finding, so both must survive into the report.
        self.assertCountEqual(
            detail["affectedConfigurations"],
            ["optim=adam, lr=0.1, batch_size=32",
             "optim=sgd, lr=0.1, batch_size=32"],
        )

    def test_findings_are_ordered_most_severe_first(self):
        severities = [f.severity for f in self.facts.findings]
        ranks = [severity_rank(s) for s in severities]
        self.assertEqual(ranks, sorted(ranks, reverse=True))

    def test_findings_cite_the_observations_that_justify_them(self):
        for finding in self.facts.findings:
            self.assertTrue(finding.based_on)
            for observation in finding.based_on:
                self.assertEqual(observation.severity, finding.severity)

    def test_severity_distribution_across_the_grid(self):
        distribution = {}
        for observation in _advantages(self.facts):
            distribution[observation.severity] = (
                distribution.get(observation.severity, 0) + 1
            )
        self.assertEqual(distribution, {"NONE": 8, "LOW": 3, "HIGH": 2})

    def test_derived_score_is_marked_and_left_unclassified(self):
        summary = _summary(self.facts, SCORE)
        self.assertEqual(summary.derived_from, ADVANTAGE)
        self.assertFalse(summary.higher_is_worse)
        # Classifying a restatement of the advantage would double-count the
        # same underlying measurement.
        scores = [o for o in self.facts.observations if o.metric == SCORE]
        self.assertTrue(all(o.severity == "NONE" for o in scores))

    def test_score_is_algebraically_redundant_with_advantage(self):
        # Documents why the ontology marks score as derived: the relation holds
        # exactly on the observed payload. If a future MIA release breaks it,
        # this test fails and the derivation claim must be revisited.
        rows, _ = parse_sweep_table(OBSERVED_SWEEP)
        for row in rows:
            self.assertAlmostEqual(
                row["score"], (1 - abs(row["adv"])) / 2, places=12
            )

    def test_replicated_grid_cell_is_kept_and_disclosed(self):
        # 13 rows over 12 cells: the replicate is noise signal, not a duplicate
        # to drop, but the row count must not read as coverage.
        self.assertEqual(len(_advantages(self.facts)), 13)
        self.assertEqual(self.facts.method["distinctConfigurations"], 12)
        self.assertTrue(
            any("replicates" in s for s in self.facts.scope_limitations)
        )

    def test_degenerate_accuracy_is_disclosed(self):
        self.assertTrue(
            any("accuracy of 1.0" in s for s in self.facts.scope_limitations)
        )

    def test_untested_surface_is_disclosed_with_numeric_ordering(self):
        grid = next(
            s for s in self.facts.scope_limitations if "were exercised" in s
        )
        self.assertIn("batch_size: 32, 64, 128", grid)
        self.assertIn("untested", grid)

    def test_method_records_sweep_provenance(self):
        method = self.facts.method
        self.assertEqual(method["rowCount"], 13)
        self.assertEqual(method["assessmentShape"], "parameterSweep")
        self.assertIn("intrust.ttl", method["thresholdSource"])
        self.assertEqual(method["tool"], "MIA service")

    def test_intent_parameters_are_carried_into_method(self):
        facts = normalize(
            {"status": "success", "data": OBSERVED_SWEEP},
            intent={
                "assessment": {
                    "parameters": {
                        "attack_type": "black_box",
                        "num_shadow_models": 8,
                    }
                },
                "criteria": ["gdpr", "internal_privacy_policy:v2"],
            },
        )
        self.assertEqual(facts.method["attack_type"], "black_box")
        self.assertEqual(facts.method["num_shadow_models"], 8)
        self.assertEqual(facts.method["criteria"], ["gdpr", "internal_privacy_policy:v2"])

    def test_serialisation_round_trips_the_figures(self):
        payload = self.facts.to_dict()
        self.assertEqual(payload["worstSeverity"], "HIGH")
        self.assertEqual(len(payload["observations"]), 26)
        self.assertEqual(payload["method"]["rowCount"], 13)
        self.assertTrue(payload["scopeLimitations"])
        high = next(f for f in payload["findings"] if f["severity"] == "HIGH")
        self.assertTrue(high["basedOn"])


class ToolVersionTest(unittest.TestCase):
    """
    The MIA version is carried from the envelope, and its provenance is stated.

    The MIA service exposes no version endpoint, so the value is pinned in
    ``tools/mia_assessment.py``.  That makes it a statement about this checkout's
    configuration rather than evidence from the service, and
    ``toolVersionSource`` is what stops a report presenting it as the latter.
    """

    def test_the_version_is_read_from_the_envelope(self):
        facts = normalize(
            {"status": "success", "version": "0.0.9", "data": OBSERVED_SWEEP}
        )
        self.assertEqual(facts.method["toolVersion"], "0.0.9")
        self.assertEqual(facts.method["toolVersionSource"], "pinned")

    def test_a_stored_result_reports_the_version_it_ran_under(self):
        # Read from the envelope rather than imported from the tool wrapper, so
        # re-normalising an older result does not relabel it with today's pin.
        from tools.mia_assessment import MIA_SERVICE_VERSION

        facts = normalize(
            {"status": "success", "version": "0.0.7", "data": OBSERVED_SWEEP}
        )
        self.assertEqual(facts.method["toolVersion"], "0.0.7")
        self.assertNotEqual(facts.method["toolVersion"], MIA_SERVICE_VERSION)

    def test_a_missing_version_is_none_not_invented(self):
        # An absent version is accurate for a result produced before the pin
        # existed; a fabricated one is a traceability claim the assessment
        # cannot support.
        facts = normalize({"status": "success", "data": OBSERVED_SWEEP})
        self.assertIsNone(facts.method["toolVersion"])
        self.assertIsNone(facts.method["toolVersionSource"])

    def test_the_tool_wrapper_pins_a_version_and_puts_it_in_the_envelope(self):
        # The constant and the envelope key have to agree, or the normalizer
        # reads a version the wrapper never sends.
        from tools.mia_assessment import MIA_SERVICE_VERSION

        self.assertEqual(MIA_SERVICE_VERSION, "0.0.9")
        facts = normalize(
            {"status": "success", "version": MIA_SERVICE_VERSION, "data": OBSERVED_SWEEP}
        )
        self.assertEqual(facts.method["toolVersion"], MIA_SERVICE_VERSION)

    def test_the_skill_forwards_the_version_to_the_orchestrator(self):
        # The orchestrator reads ``result["version"]`` for
        # ``provenance.toolVersion``; the skill dropping it is what left that
        # field empty for the composing LLM to fill.
        import skills.mia_skill as mia_skill

        class _Logger:
            def info(self, *_args, **_kwargs):
                pass

            def warning(self, *_args, **_kwargs):
                pass

            def error(self, *_args, **_kwargs):
                pass

        envelope = {"status": "success", "version": "0.0.9", "data": OBSERVED_SWEEP}
        original = mia_skill.run_mia_assessment
        mia_skill.run_mia_assessment = lambda intent, logger: envelope
        try:
            result = mia_skill.execute({"parameters": {"model": "m"}}, _Logger())
        finally:
            mia_skill.run_mia_assessment = original
        self.assertEqual(result["version"], "0.0.9")
        self.assertEqual(result["tool"], "MIA service")


class DegradationTest(unittest.TestCase):
    """A normalisation problem must never lose a completed assessment."""

    def test_mia_error_envelope_becomes_failed_fact_model(self):
        facts = normalize({"status": "error", "message": "Request timed out"})
        self.assertEqual(facts.status, "FAILED")
        self.assertIn("timed out", facts.normalization_error)

    def test_empty_data_is_inconclusive_not_an_exception(self):
        facts = normalize({"status": "success", "data": ""})
        self.assertEqual(facts.status, "INCONCLUSIVE")
        self.assertIsNotNone(facts.normalization_error)

    def test_unexpected_json_payload_is_inconclusive(self):
        facts = normalize({"status": "success", "data": {"unexpected": 1}})
        self.assertEqual(facts.status, "INCONCLUSIVE")
        self.assertIn("JSON object", facts.normalization_error)

    def test_header_only_table_is_inconclusive(self):
        facts = normalize(
            {"status": "success", "data": "model_id;optim;adv;score\n"}
        )
        self.assertEqual(facts.status, "INCONCLUSIVE")

    def test_partial_table_yields_readable_rows_and_records_the_problem(self):
        truncated = "\n".join(OBSERVED_SWEEP.splitlines()[:5] + ["broken;row"])
        facts = normalize({"status": "success", "data": truncated})
        self.assertEqual(facts.status, "SUCCESS")
        self.assertEqual(len(_advantages(facts)), 4)
        self.assertIsNotNone(facts.normalization_error)

    def test_no_findings_when_every_configuration_is_below_thresholds(self):
        clean = (
            "model_id;optim;lr;batch_size;train_acc;test_acc;adv;score\n"
            "aaa;adam;0.1;64;0.98;0.91;0.001;0.4995\n"
            "bbb;sgd;0.1;64;0.97;0.90;0.002;0.499\n"
        )
        facts = normalize({"status": "success", "data": clean})
        self.assertEqual(facts.findings, [])
        self.assertEqual(facts.worst_severity, "NONE")
        self.assertEqual(facts.status, "SUCCESS")
        # A clean sweep still discloses what it did not cover.
        self.assertTrue(facts.scope_limitations)


CLEAN_SWEEP = (
    "model_id;optim;lr;batch_size;train_acc;test_acc;adv;score\n"
    "aaa;adam;0.1;64;0.98;0.91;0.001;0.4995\n"
    "bbb;sgd;0.1;64;0.97;0.90;0.002;0.499\n"
)


def _provisional_registry(**flags):
    """
    A registry with the advantage metric's provisional flags set explicitly.

    The MIA thresholds are confirmed in the ontology, so the disclosure
    machinery can no longer be exercised by loading it.  Patching the loaded
    definition keeps the tests about the normalizer's behaviour rather than
    about the current state of one metric.
    """
    import dataclasses

    registry = load_registry()
    definition = registry.get(ADVANTAGE)
    thresholds = definition.thresholds
    if "threshold_provisional" in flags:
        thresholds = tuple(
            dataclasses.replace(
                t,
                provisional=flags["threshold_provisional"],
                provisional_reason=(
                    "The boundary has not been confirmed with the team that "
                    "owns the attack implementation."
                    if flags["threshold_provisional"]
                    else None
                ),
            )
            for t in thresholds
        )
    patched = dataclasses.replace(
        definition,
        thresholds=thresholds,
        **{
            key: value
            for key, value in flags.items()
            if key != "threshold_provisional"
        },
    )
    return type(registry)({ADVANTAGE: patched, SCORE: registry.get(SCORE)})


class ConfirmedThresholdTest(unittest.TestCase):
    """
    The MIA boundaries are confirmed, so no threshold caveat is emitted.

    Asserted positively rather than left to the absence of a test: the
    confirmation is what makes the severity words in these reports load-bearing,
    and a stray provisional flag reintroducing the caveat should fail here rather
    than be noticed in a report.
    """

    @classmethod
    def setUpClass(cls):
        cls.facts = normalize({"status": "success", "data": OBSERVED_SWEEP})
        cls.clean = normalize({"status": "success", "data": CLEAN_SWEEP})

    def test_method_records_the_thresholds_as_confirmed(self):
        # Stated positively rather than by omission: an absent key is
        # indistinguishable from an older normalizer that never checked.
        self.assertEqual(self.facts.method["provisionalThresholds"], [])
        self.assertTrue(self.facts.method["thresholdsConfirmed"])

    def test_no_threshold_caveat_reaches_the_limitations(self):
        joined = " ".join(self.facts.scope_limitations).lower()
        self.assertNotIn("severity classification in this report rests", joined)
        self.assertNotIn("provisional", joined)

    def test_no_threshold_caveat_reaches_the_external_statement(self):
        joined = " ".join(self.clean.external_scope_statement).lower()
        self.assertNotIn("provisional", joined)

    def test_the_verdict_is_unchanged_by_the_confirmation(self):
        # The confirmation settled where the boundaries are, it did not move
        # them: two configurations still exceed 0.10.
        self.assertEqual(self.facts.worst_severity, "HIGH")
        self.assertEqual(self.clean.worst_severity, "NONE")

    def test_the_limitations_that_are_about_the_sweep_survive(self):
        # Removing the caveat must not remove the entries it used to precede.
        joined = " ".join(self.facts.scope_limitations)
        self.assertIn("replicates", joined)
        self.assertIn("accuracy of 1.0", joined)
        self.assertIn("untested", joined)


class ProvisionalThresholdDisclosureTest(unittest.TestCase):
    """
    An unconfirmed severity boundary travels with every report that uses it.

    A threshold classifies a measured advantage into a severity word, and that
    word is what a reader acts on.  While a boundary is unconfirmed, a report
    stating "HIGH" without stating so is asserting more than the assessment
    establishes.  The MIA service's boundaries are confirmed now, so these run against a
    patched registry: the mechanism has to stay working for the next metric whose
    thresholds are provisional, and it was originally built because the caveat
    lived only in an ``rdfs:comment`` that no report ever showed.
    """

    @classmethod
    def setUpClass(cls):
        registry = _provisional_registry(threshold_provisional=True)
        cls.facts = normalize(
            {"status": "success", "data": OBSERVED_SWEEP}, registry=registry
        )
        cls.clean = normalize(
            {"status": "success", "data": CLEAN_SWEEP}, registry=registry
        )

    def test_method_records_the_boundaries_in_question(self):
        provisional = self.facts.method["provisionalThresholds"]
        self.assertEqual(len(provisional), 3)
        self.assertFalse(self.facts.method["thresholdsConfirmed"])
        names = {entry["thresholdName"] for entry in provisional}
        self.assertIn("MIAAdvantageHighThreshold", names)

    def test_each_entry_cites_the_individual_so_it_is_traceable(self):
        for entry in self.facts.method["provisionalThresholds"]:
            with self.subTest(name=entry["thresholdName"]):
                self.assertTrue(entry["thresholdIri"].endswith(entry["thresholdName"]))
                self.assertTrue(entry["reason"])

    def test_the_caveat_reaches_scope_limitations(self):
        # ``method`` is not in the management profile's sections, so a
        # machine-readable record alone would never reach a CISO.
        self.assertIn("provisional", self.facts.scope_limitations[0].lower())

    def test_the_caveat_comes_first_among_the_limitations(self):
        # The others qualify how far the numbers generalise; this one qualifies
        # the severity word the reader is most likely to act on.
        self.assertIn("severity", self.facts.scope_limitations[0].lower())

    def test_the_caveat_does_not_impugn_the_measurements(self):
        # The advantage figures are the tool's and are not in question.  A
        # caveat that reads as doubt about them invites dismissing the finding.
        caveat = self.facts.scope_limitations[0]
        self.assertIn("unaffected", caveat)

    def test_a_clean_sweep_carries_the_caveat_too(self):
        # A "NONE" verdict is the claim that every value fell below the
        # boundaries, so it depends on them exactly as an adverse verdict does.
        self.assertEqual(self.clean.worst_severity, "NONE")
        self.assertIn("provisional", " ".join(self.clean.scope_limitations).lower())

    def test_the_derived_metric_contributes_no_caveat(self):
        # No threshold is applied to the score column, so it has no boundary to
        # qualify; listing one would suggest a classification that never ran.
        metrics = {
            entry["metric"] for entry in self.facts.method["provisionalThresholds"]
        }
        self.assertEqual(metrics, {ADVANTAGE})

    def test_the_external_statement_discloses_it_without_the_figures(self):
        # An external artifact is released only for a clean verdict, and that
        # verdict rests on these boundaries; withholding the caveat would put it
        # only in front of the readers least likely to over-read the result.
        statement = " ".join(self.clean.external_scope_statement)
        self.assertIn("provisional", statement.lower())
        for leak in ("0.02", "0.10", "MIAAdvantage", "MIA service", "adv"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, statement)

    def test_a_confirmed_threshold_produces_no_caveat(self):
        # Mutation check: with the flag cleared the disclosure must disappear, or
        # it is unconditional text rather than a real signal.
        facts = normalize(
            {"status": "success", "data": OBSERVED_SWEEP},
            registry=_provisional_registry(
                threshold_provisional=False, semantics_provisional=False
            ),
        )
        self.assertEqual(facts.method["provisionalThresholds"], [])
        self.assertTrue(facts.method["thresholdsConfirmed"])
        self.assertNotIn("provisional", " ".join(facts.scope_limitations).lower())
        self.assertNotIn(
            "provisional", " ".join(facts.external_scope_statement).lower()
        )
        # The verdict is unchanged: the flag qualifies the boundary, it does not
        # move it.
        self.assertEqual(facts.worst_severity, "HIGH")


class ProvisionalMetricSemanticsDisclosureTest(unittest.TestCase):
    """
    The confirmation settled the boundaries, not the reading of ``adv``.

    Whether the sign of the column is directional or noise is still open, and
    that qualifies every finding resting on a negative advantage — the
    normalizer classifies on the magnitude, which treats a negative value as a
    leak of the same size.  Recorded against the metric rather than a threshold
    so it survived the threshold confirmation instead of being cleared with it.
    """

    @classmethod
    def setUpClass(cls):
        cls.facts = normalize({"status": "success", "data": OBSERVED_SWEEP})
        cls.clean = normalize({"status": "success", "data": CLEAN_SWEEP})

    def test_method_records_the_metric_whose_reading_is_open(self):
        semantics = self.facts.method["provisionalMetricSemantics"]
        self.assertFalse(self.facts.method["metricSemanticsConfirmed"])
        metrics = {entry["metric"] for entry in semantics}
        self.assertIn(ADVANTAGE, metrics)
        for entry in semantics:
            with self.subTest(metric=entry["metric"]):
                self.assertTrue(entry["reason"])

    def test_it_is_recorded_independently_of_the_thresholds(self):
        # The whole point of the split: one is confirmed and the other is not,
        # and a report must not state either as standing for both.
        self.assertTrue(self.facts.method["thresholdsConfirmed"])
        self.assertFalse(self.facts.method["metricSemanticsConfirmed"])

    def test_the_derived_metric_inherits_the_source_interpretation(self):
        # ``score`` is an algebraic restatement of ``adv``, so a doubt about how
        # ``adv`` reads is a doubt about how ``score`` reads.
        entry = next(
            e
            for e in self.facts.method["provisionalMetricSemantics"]
            if e["metric"] == SCORE
        )
        self.assertEqual(entry["interpretationOf"], ADVANTAGE)

    def test_the_caveat_reaches_scope_limitations(self):
        joined = " ".join(self.facts.scope_limitations)
        self.assertIn("not fully settled", joined)

    def test_the_caveat_states_the_reading_that_was_applied(self):
        # Without it the reader knows the metric is ambiguous but not which way
        # the assessment resolved it, which is what decides whether a finding on
        # a negative value is overstated or understated.
        caveat = next(
            s for s in self.facts.scope_limitations if "not fully settled" in s
        )
        self.assertIn("absolute value", caveat)
        self.assertIn("conservative", caveat)

    def test_the_caveat_does_not_impugn_the_measurements(self):
        caveat = next(
            s for s in self.facts.scope_limitations if "not fully settled" in s
        )
        self.assertIn("unaffected", caveat)

    def test_it_is_stated_once_for_a_metric_and_its_restatement(self):
        # Two entries in ``method``, one sentence in the prose: the reason is the
        # same, and repeating it would bury the limitations about this sweep.
        self.assertEqual(len(self.facts.method["provisionalMetricSemantics"]), 2)
        self.assertEqual(
            sum(1 for s in self.facts.scope_limitations if "not fully settled" in s),
            1,
        )

    def test_a_clean_sweep_carries_the_caveat_too(self):
        # A clean verdict rests on reading every measured value as below the
        # boundaries, so how those values read qualifies it too.
        self.assertEqual(self.clean.worst_severity, "NONE")
        self.assertIn("not fully settled", " ".join(self.clean.scope_limitations))

    def test_the_external_statement_discloses_it_without_the_internals(self):
        statement = " ".join(self.clean.external_scope_statement)
        self.assertIn("interpreted", statement)
        self.assertIn("conservative", statement)
        # The column name and the direction of the possible error are internal:
        # they let a colleague weigh a specific finding, and a released statement
        # has no specific finding to weigh.
        for leak in ("adv", "sign", "absolute value", "MIA service", "0.10"):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, statement)

    def test_confirming_the_semantics_removes_the_disclosure(self):
        # Mutation check, and the edit whoever closes this out will make: with
        # the ontology flag cleared the disclosure disappears everywhere and the
        # verdict is unchanged.
        facts = normalize(
            {"status": "success", "data": OBSERVED_SWEEP},
            registry=_provisional_registry(semantics_provisional=False),
        )
        self.assertEqual(facts.method["provisionalMetricSemantics"], [])
        self.assertTrue(facts.method["metricSemanticsConfirmed"])
        self.assertNotIn("not fully settled", " ".join(facts.scope_limitations))
        clean = normalize(
            {"status": "success", "data": CLEAN_SWEEP},
            registry=_provisional_registry(semantics_provisional=False),
        )
        self.assertNotIn(
            "interpreted", " ".join(clean.external_scope_statement)
        )
        self.assertEqual(facts.worst_severity, "HIGH")

    def test_the_ontology_pairs_every_open_interpretation_with_a_reason(self):
        # MetricDefinitionShape enforces this; this asserts it survives the load
        # for every metric, not only the advantage.
        for definition in load_registry().list():
            if definition.semantics_provisional:
                with self.subTest(metric=definition.identifier):
                    self.assertTrue(definition.semantics_provisional_reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
