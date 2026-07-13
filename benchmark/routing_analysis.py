"""
Routing decomposition — separate the ROUTING DECISION from PROTOCOL ADHERENCE.

The raw `routing_correct` metric only credits a run when the model emits a
NATIVE tool call / transfer to the expected target.  That conflates two
independent abilities:

- **Decision** — did the model identify the correct capability at all
  (whether it emitted a native call or merely described the choice in text)?
- **Native-call adherence** — did it express that decision through the
  native function-calling protocol, rather than as prose?

Many models make the right decision but fail the protocol (e.g. deepseek-r1
writes "Dispatched to: bandit-assessment-agent" as text and never calls a
tool).  Scoring only native calls makes decision-capable models look like
routing failures and — for the gatekeeping scenario — scores a
protocol-failure as a "refusal", flattering models that cannot call tools.

This module recovers the decision from the stored ``selected`` field (exact,
when a native call happened) and, failing that, from ``final_text`` (a
documented heuristic).  Native-call adherence is exact; the text-derived
decision/refusal is a heuristic and should be spot-checked against
transcripts before publication.
"""

import re
from typing import Optional, Tuple

# Gatekeeping (refuse an unsupported request) is only interpretable for a
# model that has DEMONSTRATED the ability to act — otherwise "refusing
# everything" is indistinguishable from being unable to call tools at all.
# A model's gatekeeping is reported only when its native-call adherence on
# the SUPPORTED scenarios reaches this fraction; below it, gatekeeping is
# marked "not interpretable" (e.g. deepseek-r1 emits no native calls, so its
# 100% "refusal" is incapacity, not judgment).
GATEKEEPING_MIN_NATIVE_CALL = 0.2

# Per-skill signatures used to recover the intended capability from free text.
# "native" — tool/agent identifiers as they appear in the ``selected`` field.
# "explicit" — unambiguous phrases a model uses when naming this capability.
# "keywords" — weaker hints, tried only if no explicit phrase matched.
SKILL_SIGNATURES = {
    "bandit-static-code": {
        "native": ["bandit_static_code", "bandit_static_code_agent"],
        "explicit": ["bandit", "static code analysis", "static application security"],
        "keywords": ["staticcodeanalysis"],
    },
    "trivy-filesystem": {
        "native": ["trivy_filesystem", "trivy_filesystem_agent"],
        "explicit": ["trivy_filesystem", "trivy filesystem", "filesystem scan",
                     "file system scan", "filesystem security"],
        "keywords": ["filesystem", "file system"],
    },
    "trivy-docker-image": {
        "native": ["trivy_docker_image", "trivy_docker_image_agent"],
        "explicit": ["trivy_docker_image", "docker image", "container image",
                     "image vulnerability", "image scan"],
        "keywords": ["docker", "container image"],
    },
    "trivy-kubernetes": {
        "native": ["trivy_kubernetes", "trivy_kubernetes_agent"],
        "explicit": ["trivy_kubernetes", "kubernetes", "k8s cluster"],
        "keywords": ["kubernetes", "k8s", "cluster"],
    },
}

# Phrases that indicate the model DECLINED to route (genuine gatekeeping).
REFUSAL_PHRASES = [
    "no direct match", "no matching", "no suitable", "no appropriate",
    "no available", "none of the available", "not support", "does not support",
    "cannot proceed", "unable to", "i'm sorry", "i am sorry", "no capability",
    "not currently support", "no relevant", "cannot assist", "can't assist",
    "outside the scope", "not within", "no such capability",
]


def _skill_from_native(selected: str) -> Optional[str]:
    """Map a native ``selected`` value (tool fn or agent) to its skill key."""
    token = selected.lower().removesuffix("_agent")
    for skill, sig in SKILL_SIGNATURES.items():
        for name in sig["native"]:
            if token == name.removesuffix("_agent"):
                return skill
    return None


def _skill_from_text(text: str) -> Optional[str]:
    """
    Recover the intended skill from free text: explicit phrases first, then
    keywords.  Returns a skill key, or None when nothing (or more than one,
    ambiguously) matches at the same tier.
    """
    low = text.lower()
    for tier in ("explicit", "keywords"):
        hits = [skill for skill, sig in SKILL_SIGNATURES.items()
                if any(phrase in low for phrase in sig[tier])]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            # Ambiguous at this tier — prefer the one whose native identifier
            # (most specific) is present, else give up.
            for skill in hits:
                if any(n in low for n in SKILL_SIGNATURES[skill]["native"]):
                    return skill
            return None
    return None


def _has_refusal(text: str) -> bool:
    low = text.lower()
    return any(phrase in low for phrase in REFUSAL_PHRASES)


def classify(selected: Optional[str],
             final_text: Optional[str]) -> Tuple[Optional[str], bool, bool]:
    """
    Return ``(intended_skill, native_call, refused)`` for one run.

    - ``intended_skill`` — the capability the model chose (from the native
      call if there was one, else recovered from the text), or None.
    - ``native_call`` — whether a native tool call / transfer happened.
    - ``refused`` — whether the text explicitly declined to route.
    """
    native_call = selected is not None
    if native_call:
        return _skill_from_native(selected), True, False
    text = final_text or ""
    return _skill_from_text(text), False, _has_refusal(text)


def decision_correct(intended_skill: Optional[str], native_call: bool,
                     refused: bool, expected_skill: Optional[str],
                     is_supported: bool) -> bool:
    """
    Was the routing DECISION correct, independent of native-call adherence?

    - Supported scenario: the model identified the expected skill.
    - Gatekeeping scenario: the model genuinely refused — it neither emitted
      a native call nor committed to a skill in text without also declining.
    """
    if is_supported:
        return intended_skill == expected_skill
    # Gatekeeping: correct == genuine refusal (did not route anywhere).
    committed = native_call or (intended_skill is not None and not refused)
    return not committed
