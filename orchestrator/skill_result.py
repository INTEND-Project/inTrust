# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
The result envelope an assessment skill returns.

A skill that normalises its output returns the same three things: the canonical
facts, the raw tool output they were derived from, and the status the
normalisation arrived at.  ``normalised_result`` builds that envelope so the
four skills doing it do not each define the contract slightly differently — a
skill that spelled ``facts`` differently, or omitted ``raw``, would silently
lose every audience rendition downstream in ``_standardize_report``.

The raw output is kept beside the facts rather than replaced by them.  It is
what makes a figure in a report checkable: a reader who doubts a normalised
value can re-derive it, and a normalizer that turns out to have misread its tool
can be corrected against results already stored.
"""

from __future__ import annotations

from typing import Any, Dict

from orchestrator.fact_model import FactModel


def normalised_result(
    facts: FactModel,
    raw_result: Dict[str, Any],
    assessment_type: str,
    tool: str,
    logger: Any = None,
    component: str = "skill",
) -> Dict[str, Any]:
    """
    Wrap normalised facts and the raw tool output into a skill result.

    Parameters
    ----------
    facts
        The ``FactModel`` the skill's normalizer produced.  Its ``status`` is
        the envelope's status: normalisation is what decides whether a result is
        usable, since a tool can exit successfully having produced output that
        cannot be interpreted.
    raw_result
        The unmodified tool output, retained as ``raw``.
    assessment_type, tool
        Recorded for the report envelope.
    logger
        When given, a summary of the normalisation is logged, and a partial
        normalisation is logged as a warning.  A partial result is reported
        rather than raised: a scan that found nine findings and could not read a
        tenth is still worth the nine.
    component
        Logger component name, e.g. ``"skill.bandit"``.
    """
    if logger:
        logger.info(
            component,
            f"[Normalization] shape={facts.shape} "
            f"findings={len(facts.findings)} "
            f"observations={len(facts.observations)} "
            f"worstSeverity={facts.worst_severity}",
        )
        if facts.normalization_error:
            logger.warning(
                component,
                f"[Normalization] partial result: {facts.normalization_error}",
            )

    return {
        "status": facts.status,
        "assessment_type": assessment_type,
        "tool": tool,
        "facts": facts.to_dict(),
        "raw": raw_result,
    }
