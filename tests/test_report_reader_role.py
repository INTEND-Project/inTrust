# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Tests for choosing a rendition on read, by profile name or by reader role.

Run with the stdlib runner (no pytest dependency required)::

    python -m unittest discover -s tests -v

These exercise the API rather than the projector: ``tests/test_report_profile.py``
already establishes that each profile reduces correctly, so what is left to check
is the resolution in front of it — that a role reaches the right profile, that an
unrecognised one is refused rather than defaulted, and that the choice is recorded
truthfully in the artifact.

The refusal is the test that matters.  ``resolve_profile`` falls back to
``technical`` for an intent asserting an unmapped role, and inheriting that
behaviour here would answer a misspelled role with the fullest internal rendition
— evidence, remediation steps and file paths — on the strength of a typo.  So
there is a test for the fallback *not* happening, and one asserting no findings
leak into the 400 that replaces it.

A real FastAPI app on a temporary SQLite database, driven through TestClient: the
query-parameter wiring and the HTTPException handling are exactly what is under
test, so calling the handlers directly would skip the part that can break.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

INTENT_ID = "intent-reader-role-001"
JOB_ID = "job-reader-role-001"
# Fixed rather than "now": the external profile derives an expiry from this, and
# a wall-clock value would make the assertion below drift.
ASSESSED_ON = datetime(2026, 8, 6, 10, 0, 0, tzinfo=timezone.utc)


def _stored_result():
    """A stored result with real normalised facts, as the executor writes it."""
    from test_bandit_normalizer import _facts

    facts = _facts().to_dict()
    return {
        "facts": facts,
        "regulatoryCoverage": facts.get("regulatoryCoverage") or {},
        # The issuer's own rendition.  Deliberately a sentinel: a read that
        # requests nothing must return this untouched, and a read that requests
        # a profile must replace it.
        "rendition": {"sentinel": "the issuer's stored view"},
    }


class ReaderRoleTest(unittest.TestCase):
    """``?role=`` and ``?profile=`` on the two endpoints that re-project."""

    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.mkdtemp(prefix="intrust-reader-role-")
        # Set before importing the app: the database URL is read at import time.
        os.environ.update(
            DATABASE_TYPE="sqlite",
            INTRUST_STORAGE_DIR=cls._dir,
            INTRUST_LOG_DIR=cls._dir,
            SQLITE_DATABASE_FILE="test.db",
            DATABASE_URL=f"sqlite:///{cls._dir}/test.db",
            # These tests are about which rendition a reader gets, which is
            # deterministic.  The prose summary that normally accompanies it is an
            # LLM call, so leaving it on would make every read here depend on a
            # reachable gateway and assert nothing extra.
            INTRUST_RENDITION_SUMMARY="0",
        )
        from fastapi.testclient import TestClient

        from api.database import (
            JobRecord,
            ResultRecord,
            SessionLocal,
            init_db,
        )
        from main import app

        init_db()
        db = SessionLocal()
        db.add(
            JobRecord(
                job_id=JOB_ID,
                intent_id=INTENT_ID,
                status="COMPLETED",
                created_at=ASSESSED_ON,
                completed_at=ASSESSED_ON,
            )
        )
        db.add(ResultRecord(job_id=JOB_ID, result_json=_stored_result()))
        db.commit()
        db.close()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._dir, ignore_errors=True)

    def _read(self, query=""):
        return self.client.get(f"/result/{JOB_ID}{query}")

    def _rendition(self, query=""):
        response = self._read(query)
        self.assertEqual(response.status_code, 200, msg=response.text)
        return response.json()["result"]["rendition"]

    # -- resolution ------------------------------------------------------

    def test_every_role_of_every_profile_resolves_to_it(self):
        # Read from the registry rather than a hand-copied list, so a role added
        # to a profile later is covered here without anyone remembering to.
        from orchestrator.report_profile import PROFILES

        for profile in PROFILES:
            for role in profile.roles:
                with self.subTest(profile=profile.name, role=role):
                    rendition = self._rendition(f"?role={role}")
                    self.assertEqual(
                        rendition["reportProfile"]["name"], profile.name
                    )

    def test_a_role_is_matched_case_insensitively(self):
        self.assertEqual(
            self._rendition("?role=dpo")["reportProfile"]["name"], "compliance"
        )

    def test_no_parameter_returns_the_issuers_stored_rendition(self):
        # The stored view is the issuer's; a read that asks for nothing must not
        # silently get someone else's.
        self.assertEqual(
            self._rendition(), {"sentinel": "the issuer's stored view"}
        )

    def test_profile_wins_when_both_are_given(self):
        rendition = self._rendition("?profile=management&role=Developer")
        self.assertEqual(rendition["reportProfile"]["name"], "management")

    # -- the refusal -----------------------------------------------------

    def test_an_unrecognised_role_is_refused_not_defaulted(self):
        # The whole point.  A typo must not resolve to the fullest rendition.
        response = self._read("?role=Custmoer")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown reader role", response.json()["detail"])

    def test_the_refusal_discloses_nothing_about_the_assessment(self):
        # A 400 that quoted the facts it declined to project would defeat itself.
        body = self._read("?role=Attacker").text
        facts = _stored_result()["facts"]
        for finding in facts.get("findings") or []:
            self.assertNotIn(str(finding.get("title")), body)
        self.assertNotIn("findings", body)

    def test_an_unknown_profile_is_still_refused(self):
        response = self._read("?profile=marketing")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown report profile", response.json()["detail"])

    def test_an_empty_role_is_treated_as_absent(self):
        # ``?role=`` with no value is not an unrecognised role; it is no request
        # at all, and answering it with a 400 would be a surprise.
        self.assertEqual(
            self._rendition("?role="), {"sentinel": "the issuer's stored view"}
        )

    # -- the recorded basis ----------------------------------------------

    def test_the_rendition_records_that_a_role_was_asked_for(self):
        # Not "requested profile=compliance": how the rendition was chosen is
        # what a reader asking why their report looks like this needs, and the
        # two routes to one profile are different answers.
        rendition = self._rendition("?role=DPO")
        self.assertEqual(
            rendition["reportProfile"]["resolvedBy"], "reader role=DPO"
        )

    def test_the_recorded_role_is_trimmed(self):
        rendition = self._rendition("?role=%20%20DPO%20%20")
        self.assertEqual(
            rendition["reportProfile"]["resolvedBy"], "reader role=DPO"
        )

    def test_a_profile_request_records_the_profile(self):
        rendition = self._rendition("?profile=compliance")
        self.assertEqual(
            rendition["reportProfile"]["resolvedBy"],
            "requested profile=compliance",
        )

    # -- the rendition is genuinely the projected one ---------------------

    def test_a_role_read_is_validated_against_the_shapes(self):
        # The stored validation belongs to the issuer's profile; a rendition
        # produced for a different reader must be checked in its own right.
        response = self._read("?role=DPO")
        self.assertTrue(
            response.json()["result"]["renditionValidation"]["conforms"]
        )

    def test_roles_serving_different_profiles_get_different_detail(self):
        # Guards against the parameter being accepted and then ignored.
        engineer = self._rendition("?role=Developer")
        executive = self._rendition("?role=CISO")
        self.assertIn("observations", engineer)
        self.assertNotIn("observations", executive)

    def test_an_external_reader_gets_the_gated_statement(self):
        # No approval was recorded for this job, so the statement is withheld
        # even though the reader asked as Sales.  The role selects a rendition;
        # it does not satisfy a gate.
        rendition = self._rendition("?role=Sales")
        self.assertFalse(rendition["released"])
        self.assertTrue(rendition["withheldBecause"])

    def test_an_external_reader_receives_no_findings(self):
        rendition = self._rendition("?role=Customer")
        self.assertNotIn("findings", rendition)
        self.assertNotIn("observations", rendition)

    # -- the TMF921 endpoint behaves the same -----------------------------

    def test_the_report_endpoint_accepts_a_role(self):
        response = self.client.get(
            f"/intent/{INTENT_ID}/intentReport/{JOB_ID}?role=DPO"
        )
        self.assertEqual(response.status_code, 200, msg=response.text)
        rendition = response.json()["result"]["rendition"]
        self.assertEqual(rendition["reportProfile"]["name"], "compliance")
        self.assertEqual(
            rendition["reportProfile"]["resolvedBy"], "reader role=DPO"
        )

    def test_the_report_endpoint_refuses_an_unrecognised_role(self):
        # Both endpoints re-project, so both need the guard; one of them having
        # it is worse than neither, because the gap is invisible.
        response = self.client.get(
            f"/intent/{INTENT_ID}/intentReport/{JOB_ID}?role=Custmoer"
        )
        self.assertEqual(response.status_code, 400)

    # -- discoverability --------------------------------------------------

    def test_the_profiles_endpoint_lists_the_roles_a_reader_may_pass(self):
        # An unrecognised role is refused, so the recognised ones have to be
        # discoverable or the refusal is a dead end.
        listed = self.client.get("/reportProfiles").json()
        for entry in listed:
            self.assertTrue(entry["roles"], msg=entry["name"])
        self.assertIn(
            "DPO",
            [role for entry in listed for role in entry["roles"]],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
