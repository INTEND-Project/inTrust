# Copyright (c) 2026 Ericsson AB
# SPDX-License-Identifier: MIT
"""
Masking of secret material in assessment evidence.

A finding about a hardcoded credential has to name where the credential is
without reproducing it.  The tools do not agree on this: Trivy masks the value
it matched, Bandit reports it in cleartext, and neither masks the *neighbouring*
source lines they include for context.

The masking happens at normalisation, where the canonical facts are built, and
not at projection.  Three reasons:

* The canonical facts are stored and can be re-projected later for a different
  audience.  A secret admitted into them outlives both the scan and any
  judgement about who should see it.
* Projection is field selection, so it has exactly one lever for evidence:
  include it or drop it.  Dropping it costs the technical reader the location
  they need; including it would carry the value.  Masking is the only option
  that serves both.
* A credential in a scanned repository is already exposed to everyone with
  repository access.  Copying it into a report widens that exposure to everyone
  with report access, which is a different and usually larger set.

What is preserved is what a reader acts on: the file, the line, the rule and
the severity.  What is removed is the value itself, which they can read from
the source if they have access to it.
"""

from __future__ import annotations

import re

# A quoted string literal, single- or double-quoted, honouring backslash escapes
# so an escaped quote inside the value does not end the match early.
_QUOTED_LITERAL = re.compile(r"(['\"])((?:[^'\"\\]|\\.)*?)\1")

# Substituted for a masked value.  Fixed width, so the length of the original is
# not disclosed either — a length is a meaningful hint about a key's format.
MASK = "****"

# Set on an evidence dict whose contents were altered here, so a reader does not
# conclude the source literally contains the mask.
REDACTION_NOTE = (
    "Quoted values in this snippet were masked during normalisation, including "
    "on context lines the tool did not flag. The value is not carried into the "
    "assessment record; read the source at the location given above to see it."
)


def mask_quoted_values(text: str) -> str:
    """
    Replace the contents of every quoted literal in ``text`` with ``MASK``.

    Every literal is masked, not only the one the tool pointed at, because tools
    report the flagged line together with its neighbours and the assignment next
    to a credential is commonly another credential.  Some harmless values are
    masked as a result; that is the intended trade, since deciding which of a
    file's literals are sensitive is exactly the judgement the scanner was run
    to make and cannot be re-made from the snippet alone.

    Structure is preserved — variable names, operators, comments and quote style
    all survive — so the snippet still shows what kind of statement was flagged.
    """
    if not text:
        return text
    return _QUOTED_LITERAL.sub(
        lambda match: f"{match.group(1)}{MASK}{match.group(1)}", text
    )
