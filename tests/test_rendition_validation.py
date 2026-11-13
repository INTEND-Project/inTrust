# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Tests for SHACL validation of audience renditions.

Run with the stdlib runner (no pytest dependency required)::

    python -m unittest discover -s tests -v

Two kinds of test here, and the second kind is the one that matters.  The
positive tests assert that every real rendition of every real fixture conforms —
cheap, and they catch a shape that is stricter than the projector.  The negative
tests corrupt a conforming rendition one field at a time and assert the specific
violation fires; a shape that cannot fail is not validating anything, and the
external-statement shapes exist precisely to catch the case where a projection
bug puts a measurement into a customer-facing artifact.
"""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator.report_profile import PROFILES, project  # noqa: E402
from tools.rendition_validation import (  # noqa: E402
    validate_rendition,
    validate_renditions,
)

import test_bandit_normalizer as bandit_fixtures  # noqa: E402
import test_trivy_normalizer as trivy_fixtures  # noqa: E402
from test_mia_normalizer import CLEAN_SWEEP, OBSERVED_SWEEP  # noqa: E402
from tools.mia_normalizer import normalize as mia_normalize  # noqa: E402

_BY_NAME = {profile.name: profile for profile in PROFILES}

# What the API supplies when it re-projects: the job's date, and the recorded
# approval.  Both are required for external release, so a rendition built
# without them is a withheld one — which is why the positive tests below pass
# them and the negative tests remove them one at a time.
ASSESSED_ON = "2026-08-06T10:00:00+00:00"
APPROVAL = {
    "state": "approved",
    "approvedBy": "release-board",
    "recordedAt": "2026-08-06T12:00:00+00:00",
    "reference": "CR-1234",
}


def _facts_for_every_shape():
    """One fact model per skill and per verdict, so both shapes are covered."""
    return {
        "mia-high": mia_normalize(
            {"status": "success", "data": OBSERVED_SWEEP}
        ).to_dict(),
        "mia-clean": mia_normalize(
            {"status": "success", "data": CLEAN_SWEEP}
        ).to_dict(),
        "bandit": bandit_fixtures._facts().to_dict(),
        "trivy": trivy_fixtures._facts().to_dict(),
    }


def _render(facts, profile_name, **kwargs):
    kwargs.setdefault("assessed_on", ASSESSED_ON)
    kwargs.setdefault("approval", APPROVAL)
    return project(
        facts, _BY_NAME[profile_name], resolved_by="actor.role", **kwargs
    )


class EveryRealRenditionConformsTest(unittest.TestCase):
    """
    The projector and the shapes must agree on every fixture.

    Both result shapes and both verdicts, because the interesting divergences
    are conditional: an external statement is structurally different when
    withheld, and a sweep reduces by aggregation where a finding list reduces by
    selection.
    """

    def test_all_profiles_of_all_fixtures_conform(self):
        for label, facts in _facts_for_every_shape().items():
            for profile in PROFILES:
                with self.subTest(fixture=label, profile=profile.name):
                    result = validate_rendition(
                        project(
                            facts,
                            profile,
                            resolved_by="actor.role",
                            assessed_on=ASSESSED_ON,
                            approval=APPROVAL,
                        )
                    )
                    self.assertEqual(result["status"], "SUCCESS")
                    self.assertTrue(
                        result["conforms"],
                        msg=[v["message"] for v in result["violations"]],
                    )

    def test_the_summary_reports_how_many_were_actually_checked(self):
        # ``allConform: true`` must not be readable as "everything was checked"
        # when a rendition was skipped.
        facts = _facts_for_every_shape()["bandit"]
        summary = validate_renditions(
            {
                "technical": _render(facts, "technical"),
                "broken": {"error": "projection blew up"},
            }
        )
        self.assertTrue(summary["allConform"])
        self.assertEqual(summary["checkedCount"], 1)
        self.assertEqual(summary["notCheckedCount"], 1)


class ExternalStatementConstraintTest(unittest.TestCase):
    """
    The release conditions, restated as shapes.

    ``project_external`` already enforces these.  Validating them again is
    deliberate: a gate enforced in one function protects only the callers that
    go through it, and a rendition can reach the store by other routes — an
    older stored result, a future caller, a hand-edited record.
    """

    @classmethod
    def setUpClass(cls):
        facts = _facts_for_every_shape()
        cls.released = _render(facts["mia-clean"], "external")
        cls.withheld = _render(facts["mia-high"], "external")

    def test_the_fixtures_are_the_two_external_cases(self):
        self.assertTrue(self.released["released"])
        self.assertFalse(self.withheld["released"])

    def _violations(self, rendition):
        result = validate_rendition(rendition)
        self.assertEqual(result["status"], "SUCCESS")
        return result["conforms"], " ".join(
            v["message"] or "" for v in result["violations"]
        )

    def test_a_released_statement_without_scope_is_rejected(self):
        # The gate that a clean verdict is only releasable alongside the bounds
        # of the search that produced it.
        bad = copy.deepcopy(self.released)
        bad["scopeStatement"] = []
        conforms, messages = self._violations(bad)
        self.assertFalse(conforms)
        self.assertIn("externalScopeStatement", messages)

    def test_a_withheld_statement_without_a_reason_is_rejected(self):
        # An unexplained absence is indistinguishable from an assessment that
        # was never run.
        bad = copy.deepcopy(self.withheld)
        bad["withheldBecause"] = []
        conforms, messages = self._violations(bad)
        self.assertFalse(conforms)
        self.assertIn("withheldBecause", messages)

    def test_an_external_statement_carrying_a_finding_count_is_rejected(self):
        # A count of what was found is a measurement of the target: "9 findings,
        # none released" discloses exactly what the allowlist withholds.
        bad = copy.deepcopy(self.released)
        bad["reportProfile"]["canonicalFindingCount"] = 9
        conforms, messages = self._violations(bad)
        self.assertFalse(conforms)
        self.assertIn("disclosure about the target", messages)

    def test_a_release_on_an_adverse_verdict_is_rejected(self):
        bad = copy.deepcopy(self.withheld)
        bad["released"] = True
        bad["scopeStatement"] = ["A bounded set of configurations was measured."]
        bad["reportProfile"]["canonicalWorstSeverity"] = "HIGH"
        conforms, messages = self._violations(bad)
        self.assertFalse(conforms)
        self.assertIn("above NONE", messages)

    def test_an_external_statement_with_exact_numerics_is_rejected(self):
        bad = copy.deepcopy(self.released)
        bad["reportProfile"]["numericDisclosure"] = "exact"
        conforms, messages = self._violations(bad)
        self.assertFalse(conforms)
        self.assertIn("verdictOnly", messages)


class ValidityAndApprovalConstraintTest(unittest.TestCase):
    """
    Expiry and approval, restated as shapes.

    Both are gates in ``project_external``, and both are stated again here for
    the artifact that reached the graph some other way.  The cases worth catching
    are a statement that cannot expire and one released without the approval it
    advertises requiring — each reads as a control while being none.
    """

    @classmethod
    def setUpClass(cls):
        cls.released = _render(_facts_for_every_shape()["mia-clean"], "external")

    def _violations(self, rendition):
        result = validate_rendition(rendition)
        self.assertEqual(result["status"], "SUCCESS")
        return result["conforms"], " ".join(
            v["message"] or "" for v in result["violations"]
        )

    def test_the_fixture_is_a_released_statement(self):
        self.assertTrue(self.released["released"])

    def test_a_released_statement_without_an_expiry_is_rejected(self):
        bad = copy.deepcopy(self.released)
        bad.pop("validUntil")
        conforms, messages = self._violations(bad)
        self.assertFalse(conforms)
        self.assertIn("statementValidUntil", messages)

    def test_a_released_statement_without_an_assessment_date_is_rejected(self):
        # No date, no expiry: a validity period has to be measured from
        # somewhere.
        bad = copy.deepcopy(self.released)
        bad.pop("assessedOn")
        conforms, messages = self._violations(bad)
        self.assertFalse(conforms)
        self.assertIn("assessedOn", messages)

    def test_an_expiry_before_the_assessment_is_rejected(self):
        # Catches a negative validity period and a date copied from the wrong
        # field.
        bad = copy.deepcopy(self.released)
        bad["validUntil"] = "2020-01-01T00:00:00+00:00"
        conforms, messages = self._violations(bad)
        self.assertFalse(conforms)
        self.assertIn("later than", messages)

    def test_an_expiry_equal_to_the_assessment_is_rejected(self):
        # A statement valid for zero time is not a statement.
        bad = copy.deepcopy(self.released)
        bad["validUntil"] = bad["assessedOn"]
        self.assertFalse(self._violations(bad)[0])

    def test_dates_are_compared_chronologically_not_lexically(self):
        # Offsets are where string comparison and chronology part company.  This
        # pair is five hours apart the right way round, so it must conform;
        # compared as text, "09:00-05:00" sorts before "10:00+00:00" and a
        # lexical check would reject a perfectly good statement.  Hence the
        # xsd:dateTime typing in the JSON-LD context.
        good = copy.deepcopy(self.released)
        good["assessedOn"] = "2026-11-04T10:00:00+00:00"
        good["validUntil"] = "2026-11-04T09:00:00-05:00"
        conforms, messages = self._violations(good)
        self.assertTrue(conforms, msg=messages)

    def test_releasing_unapproved_while_requiring_approval_is_rejected(self):
        # The case the flag existed for before anything consumed it.
        bad = copy.deepcopy(self.released)
        bad["reportProfile"]["approvalState"] = "pending"
        bad["reportProfile"].pop("approvedBy")
        conforms, messages = self._violations(bad)
        self.assertFalse(conforms)
        self.assertIn("approved", messages)

    def test_an_approval_without_an_approver_is_rejected(self):
        bad = copy.deepcopy(self.released)
        bad["reportProfile"].pop("approvedBy")
        conforms, messages = self._violations(bad)
        self.assertFalse(conforms)
        self.assertIn("spa:approvedBy", messages)

    def test_an_approver_without_an_approval_is_rejected(self):
        # The other direction: a name recorded against no decision.
        bad = copy.deepcopy(self.released)
        bad["reportProfile"]["approvalState"] = "pending"
        self.assertFalse(self._violations(bad)[0])

    def test_an_anonymous_approval_on_a_withheld_statement_is_rejected(self):
        # This is what the approved/approver pairing constraint is *for*, and it
        # is not reachable through a released statement: the release constraint
        # already covers those.  The real case is approval given while some other
        # gate withholds — the statement then records "approved" on an artifact
        # nobody is attached to.  ``project_external`` had exactly this defect
        # until this shape reported it.
        bad = copy.deepcopy(
            _render(_facts_for_every_shape()["mia-high"], "external")
        )
        self.assertFalse(bad["released"])
        bad["reportProfile"].pop("approvedBy")
        conforms, messages = self._violations(bad)
        self.assertFalse(conforms)
        self.assertIn("spa:approvedBy", messages)

    def test_an_unrecognised_approval_state_is_rejected(self):
        # There is no rejected state: a refused release is not released, and the
        # reason belongs in withheldBecause with every other unmet condition.
        bad = copy.deepcopy(self.released)
        bad["reportProfile"]["approvalState"] = "rejected"
        self.assertFalse(self._violations(bad)[0])

    def test_a_withheld_statement_needs_no_dates(self):
        # The dates gate release; an artifact that was not released has nothing
        # to expire, so requiring them there would be noise.
        withheld = _render(
            _facts_for_every_shape()["mia-high"], "external", approval=None
        )
        self.assertFalse(withheld["released"])
        self.assertTrue(self._violations(withheld)[0])


class InternalRenditionConstraintTest(unittest.TestCase):
    """A reduced rendition must stay reconcilable against its fact model."""

    @classmethod
    def setUpClass(cls):
        cls.facts = _facts_for_every_shape()["mia-high"]
        cls.management = _render(cls.facts, "management")

    def _conforms(self, rendition):
        result = validate_rendition(rendition)
        self.assertEqual(result["status"], "SUCCESS")
        return result["conforms"], " ".join(
            v["message"] or "" for v in result["violations"]
        )

    def test_dropping_the_canonical_count_is_rejected(self):
        # A management view showing two findings against a canonical nine is
        # transparently a selection; the same view without the count reads as a
        # complete list.
        bad = copy.deepcopy(self.management)
        bad["reportProfile"].pop("canonicalFindingCount")
        conforms, messages = self._conforms(bad)
        self.assertFalse(conforms)
        self.assertIn("reconciled", messages)

    def test_omitting_more_findings_than_existed_is_rejected(self):
        bad = copy.deepcopy(self.management)
        bad["reportProfile"]["findingsOmitted"] = 99
        conforms, messages = self._conforms(bad)
        self.assertFalse(conforms)
        self.assertIn("cannot omit more findings", messages)

    def test_an_unrecognised_profile_name_is_rejected(self):
        bad = copy.deepcopy(self.management)
        bad["reportProfile"]["name"] = "marketing"
        self.assertFalse(self._conforms(bad)[0])

    def test_an_invalid_severity_token_is_rejected(self):
        bad = copy.deepcopy(self.management)
        bad["reportProfile"]["canonicalWorstSeverity"] = "SEVERE"
        self.assertFalse(self._conforms(bad)[0])

    def test_a_missing_resolution_basis_is_rejected(self):
        # A detail level with no recorded basis cannot be checked against the
        # intent that asked for it.
        bad = copy.deepcopy(self.management)
        bad["reportProfile"].pop("resolvedBy")
        self.assertFalse(self._conforms(bad)[0])


class ValidatorBehaviourTest(unittest.TestCase):
    """The validator reports; it does not enforce, mutate, or raise."""

    def test_a_failed_projection_is_skipped_not_reported_as_non_conformant(self):
        # There is no artifact to validate; calling it a shape violation would
        # misattribute the failure to the shapes.
        result = validate_rendition({"error": "projection failed"})
        self.assertEqual(result["status"], "SKIPPED")
        self.assertNotIn("conforms", result)

    def test_a_non_dict_is_reported_not_raised(self):
        self.assertEqual(validate_rendition("not a rendition")["status"], "FAILED")

    def test_validation_does_not_mutate_the_rendition(self):
        rendition = _render(_facts_for_every_shape()["bandit"], "technical")
        before = copy.deepcopy(rendition)
        validate_rendition(rendition)
        self.assertEqual(rendition, before)

    def test_the_result_says_a_rendition_was_validated(self):
        # The delegate validates an "intent"; a stored envelope claiming an
        # intent was checked when a rendition was would be misleading.
        result = validate_rendition(
            _render(_facts_for_every_shape()["trivy"], "compliance")
        )
        self.assertEqual(result["validated"], "rendition")
        self.assertEqual(result["renditionProfile"], "compliance")

    def test_validation_is_deterministic(self):
        rendition = _render(_facts_for_every_shape()["mia-high"], "technical")
        first = validate_rendition(rendition)
        second = validate_rendition(rendition)
        self.assertEqual(first["conforms"], second["conforms"])
        self.assertEqual(first["violation_count"], second["violation_count"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
