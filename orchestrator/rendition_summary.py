# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Audience-specific prose, derived from a rendition rather than from facts.

``summarise_rendition`` takes the *projected* rendition as its sole factual
input.  A summary therefore cannot state anything its profile withheld: the
deterministic reduction has already happened, and what was dropped is not among
this function's arguments to leak.  This is what makes two profiles' prose
non-contradicting for the same reason their renditions are — not because a model
was asked to be consistent, but because neither was shown the other's material.

The alternative — one narrative generated from ``facts`` and reused for every
audience, or four narratives generated from ``facts`` in one call — cannot offer
that.  Compression *is* interpretation: a model handed the canonical facts and
asked for an executive summary has to decide for itself whether four
floor-suppressed LOW findings read as "no significant issues" or as "four
findings below threshold", and nothing constrains it to decide the same way
twice or the same way the technical rendition did.  Projecting first removes the
decision rather than restating it as an instruction.

Two renditions have nothing to describe and are refused rather than narrated:

- A failed projection (``{"error": ...}``) — there is no rendition to summarise,
  and prose composed from the error text would read as an assessment finding.
- A withheld external statement (``released`` is ``False``) — its entire content
  is that nothing was released.  Narrating it would produce exactly the softened
  version the release gate exists to prevent.

Non-conformance is not in that list, deliberately.  A rendition that violates a
SHACL shape is evidence of a projection bug, and the prose is part of that
evidence; it is summarised and the warning travels with it, on the same
reasoning that keeps a non-conforming rendition in the envelope instead of
discarding it.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google import genai

from orchestrator.report_profile import ReportProfile


_DISABLED_VALUES = {"0", "false", "no", "off"}


def _default_model() -> str:
    """
    The model used to compose summaries.

    Taken from the ADK agent's own model so the switchboard in
    ``orchestrator/agent.py`` stays the single place a model is chosen; naming it
    here as well would let the two drift, which is exactly what happened to the
    formal-report constant.  ``RENDITION_SUMMARY_MODEL`` overrides it for a
    deployment that wants the prose written by something other than the model
    running the assessment.

    Imported lazily and resolved per call: ``orchestrator.agent`` builds
    ``root_agent`` at import time, so importing it at module scope would pull skill
    loading and model configuration into anything that merely wants to fingerprint
    a rendition.  By the time a summary is actually composed the module is already
    loaded, so this costs a dict lookup.
    """
    configured = os.getenv("RENDITION_SUMMARY_MODEL")
    if configured:
        return configured
    from orchestrator.agent import MODEL

    return MODEL


def summaries_enabled() -> bool:
    """
    Whether prose summaries are composed at all (``INTRUST_RENDITION_SUMMARY``).

    Enabled by default, and switchable off for two reasons that matter.  An
    operator may not want an LLM call on the read path — every cache miss is one,
    including one per profile per assessment.  And a test, or any deployment
    without a reachable gateway, must still be able to read a result: the
    rendition is deterministic and needs nothing from a model, so a missing
    gateway should cost the prose and not the report.

    Read per call rather than captured at import, so a test can toggle it after
    the module is loaded.
    """
    return (
        os.getenv("INTRUST_RENDITION_SUMMARY") or "1"
    ).strip().lower() not in _DISABLED_VALUES

# Fields that vary between two reads of the *same* rendition and so must not
# enter the cache fingerprint.
#
# ``reportProfile.resolvedBy`` is the important one: "reader role=DPO" and
# "requested profile=compliance" are the same rendition arrived at two different
# ways, and treating them as different inputs would regenerate prose for a view
# that has not changed — reintroducing per-read generation with extra steps.
#
# ``assessedOn`` / ``validUntil`` move with the clock on a released external
# statement.  The statement they date is unchanged, so they are excluded too.
_VOLATILE_TOP_LEVEL = ("assessedOn", "validUntil")


def _now_iso() -> str:
    """UTC timestamp for the generation record."""
    return datetime.now(timezone.utc).isoformat()


def rendition_fingerprint(rendition: Dict[str, Any]) -> str:
    """
    Stable hash of a rendition's *content*, ignoring how it was asked for.

    Used as the cache key alongside ``(job_id, profile)`` so a stored summary is
    reused only while the rendition it describes is byte-identical, and
    invalidated automatically if a projector change alters that rendition.
    """
    stripped = {
        key: value
        for key, value in rendition.items()
        if key not in _VOLATILE_TOP_LEVEL
    }
    report_profile = stripped.get("reportProfile")
    if isinstance(report_profile, dict):
        stripped["reportProfile"] = {
            key: value
            for key, value in report_profile.items()
            if key != "resolvedBy"
        }
    canonical = json.dumps(stripped, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------

# Rules that apply to every register.  The omission rules are the ones that earn
# their place: a rendition states both what it kept and how much it dropped, and
# a summary that reports only the former turns a reduced view into a clean bill
# of health.
_BASE_RULES = """\
You write the human-readable summary that accompanies one audience's view of an
InTrust trustworthiness assessment.

Rules, in order of importance:

1. Use ONLY the JSON below. It is the complete rendition this reader receives.
   Do not infer, estimate or supply anything that is not present in it — not a
   severity, not a finding identifier, not a count, not a remediation step.
2. If `reportProfile.findingsOmitted` is greater than zero, say so explicitly
   and say it is an omission of this view. NEVER write that nothing was found,
   that the target is clean, or that there are no issues when findings were
   omitted: they were withheld from this view, not absent from the assessment.
3. If `observationReduction` is present, state that observations were reduced
   and how (it names the reduction).
4. If `scopeLimitations` is present, state them. They record what the
   assessment does not establish, and a summary that drops them reads as
   broader coverage than was achieved.
5. Do not compare this view to any other audience's view, and do not speculate
   about what another reader would see.
6. Reconcile against `reportProfile.canonicalWorstSeverity` and
   `canonicalFindingCount` when you cite totals, so the prose agrees with the
   figures beside it.

Write GitHub-flavoured Markdown. Start at a level-2 heading (`##`). No preamble,
no code fence around the whole document, no closing commentary about yourself.
"""

# Register-specific guidance.  These change tone, length and what gets led with
# — never which facts are available, which the projection already settled.
_REGISTER_GUIDANCE: Dict[str, str] = {
    "engineer": """\
Register: engineer. Write for a developer or security auditor who will act on
this. Lead with the verdict and the worst severity, then the findings that
matter and what to do about them. Name components, versions and identifiers
exactly as the rendition gives them. Technical vocabulary is expected; brevity
matters more than completeness of prose — the reader has the structured data.
Aim for 150-300 words.
""",
    "executive": """\
Register: executive. Write for a CISO or senior manager deciding whether this
needs attention or budget. Lead with the verdict in one sentence, then the
business consequence, then whether action is required. No identifiers, no
package versions, no remediation commands. Numbers may be banded rather than
exact if the rendition presents them that way — do not sharpen them. Aim for
100-180 words.
""",
    "compliance": """\
Register: compliance. Write for a compliance officer, DPO or auditor. Lead with
which obligations the assessment evidences and which it does not. State the
method and the thresholds the rendition names, because a conclusion without its
method is not auditable. Be explicit about the difference between an obligation
that was assessed and found satisfied, and one that was never assessed. Aim for
180-320 words.
""",
    "external": """\
Register: external. Write for a reader outside the organisation. State only
what the released statement contains — nothing about internal findings,
evidence, remediation or tooling detail beyond what the rendition names. Include
the validity dates, because the claim expires. Plain, careful, non-promotional
language; make no claim broader than the stated scope. Aim for 80-150 words.
""",
}


def _build_prompt(rendition: Dict[str, Any], profile: ReportProfile) -> str:
    """Assemble the summarisation prompt for one rendition."""
    guidance = _REGISTER_GUIDANCE.get(
        profile.register,
        "Register: neutral. Write plainly for a general internal reader.\n",
    )
    return (
        f"{_BASE_RULES}\n{guidance}\n"
        f"Rendition for the {profile.name!r} profile:\n\n"
        f"{json.dumps(rendition, indent=2, default=str)}\n"
    )


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _skipped(reason: str, profile: ReportProfile) -> Dict[str, Any]:
    """A rendition with nothing to describe."""
    return {
        "status": "SKIPPED",
        "reason": reason,
        "profile": profile.name,
        "register": profile.register,
    }


async def summarise_rendition(
    rendition: Dict[str, Any],
    profile: ReportProfile,
    model: Optional[str] = None,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compose the prose summary for one already-projected rendition.

    Returns a dict carrying ``status`` and, on success, ``markdown``.  Never
    raises: a summarisation failure is reported in the envelope rather than
    propagated, on the same reasoning that keeps a projection failure from
    costing an otherwise-complete assessment.

    ``warnings`` are carried through onto the result — used to attach the
    non-conformance notice, so a reader of the prose learns that the rendition
    it describes violates a shape.
    """
    if not summaries_enabled():
        return _skipped(
            "prose summaries are disabled (INTRUST_RENDITION_SUMMARY)", profile
        )
    if not isinstance(rendition, dict):
        return _skipped("no rendition to summarise", profile)
    if rendition.get("error"):
        return _skipped(
            "the projection failed, so there is no rendition to summarise",
            profile,
        )
    if rendition.get("released") is False:
        return _skipped(
            "the external statement was withheld; its content is that nothing "
            "was released, which prose would only soften",
            profile,
        )

    chosen_model = model or _default_model()
    try:
        client = genai.Client()
        response = await client.aio.models.generate_content(
            model=chosen_model,
            contents=_build_prompt(rendition, profile),
        )
        markdown = response.text
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "FAILED",
            "error": str(exc),
            "profile": profile.name,
            "register": profile.register,
            "model": chosen_model,
        }

    if not markdown or not str(markdown).strip():
        return {
            "status": "FAILED",
            "error": "the model returned an empty summary",
            "profile": profile.name,
            "register": profile.register,
            "model": chosen_model,
        }

    result: Dict[str, Any] = {
        "status": "SUCCESS",
        "markdown": str(markdown).strip(),
        "profile": profile.name,
        "register": profile.register,
        "model": chosen_model,
        "generatedAt": _now_iso(),
    }
    if warnings:
        result["warnings"] = list(warnings)
    return result
