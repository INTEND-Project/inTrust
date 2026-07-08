"""
Benchmark scenarios — the fixed assessment tasks that every architecture and
every model must execute.

Each scenario couples:
- a set of frozen TM Forum intent VARIANTS (JSON files under
  ``benchmark/data/intents/``, matched by filename prefix),
- the skill the orchestrator is EXPECTED to select for those intents, and
- the corresponding tool-function / specialist-agent names used to verify
  routing in each architecture.

Why several intent variants per scenario: the benchmark decodes greedily
(temperature 0), so repeated runs of ONE frozen intent are near
deterministic — per-cell routing accuracy would be a single routing
decision observed N times.  With five variants (different targets, varied
phrasing) each cell contains five genuine routing decisions, making routing
accuracy a robustness measure across intent formulations.  Runs rotate
through the variants (``run_idx % len(intents)``), and both architectures
see the identical variant set.

The intents and their input data are committed to the repository so that all
experiments operate on byte-identical inputs (reproducibility requirement).
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .config import REPO_ROOT

# Directory holding the frozen intent JSON files.
_INTENTS_DIR = Path(__file__).resolve().parent / "data" / "intents"


@dataclass(frozen=True)
class Scenario:
    """One benchmark scenario: fixed intent variants plus expected routing."""

    # Scenario key as used in the config file, e.g. "bandit_static_code".
    name: str
    # The frozen intent variants; runs rotate through them by run index.
    intents: Tuple[Dict[str, Any], ...]
    # Production skill name expected to be selected (e.g. "bandit-static-code").
    expected_skill: str
    # Tool function name in the single-agent architecture (skill name with
    # hyphens replaced by underscores — see skill_loader._make_skill_tool).
    expected_tool_fn: str
    # Specialist agent name in the multi-agent architecture.
    expected_agent: str


# Maps scenario key -> (intent filename prefix, expected production skill).
# All files matching ``<prefix>*.json`` are loaded (sorted) as the variant
# set — scenarios with a single intent file simply yield one variant.
_SCENARIO_TABLE = {
    "bandit_static_code": ("intent_bandit", "bandit-static-code"),
    "trivy_filesystem": ("intent_trivy_fs", "trivy-filesystem"),
    "trivy_docker_image": ("intent_trivy_image", "trivy-docker-image"),
    "trivy_kubernetes": ("intent_trivy_k8s", "trivy-kubernetes"),
}


def _resolve_paths(intent: Dict[str, Any]) -> Dict[str, Any]:
    """
    Make file-system paths inside an intent absolute.

    The frozen intents reference inputs relative to the repository root
    (e.g. ``benchmark/data/sample_code``).  Resolving them here means the
    benchmark works no matter which directory it is launched from — one of
    the reproducibility requirements (no hardcoded absolute paths in data).
    """
    params = intent.get("parameters", {})

    # Bandit: parameters.codeReference.path
    code_ref = params.get("codeReference")
    if isinstance(code_ref, dict) and code_ref.get("path"):
        p = Path(code_ref["path"])
        if not p.is_absolute():
            code_ref["path"] = str(REPO_ROOT / p)

    # Trivy filesystem: parameters.fsPath
    fs_path = params.get("fsPath")
    if fs_path:
        p = Path(fs_path)
        if not p.is_absolute():
            params["fsPath"] = str(REPO_ROOT / p)

    return intent


def load_scenarios(enabled: List[str]) -> List[Scenario]:
    """
    Load the Scenario objects for the scenario keys enabled in the config.

    Parameters
    ----------
    enabled : list of str
        Scenario keys from the config file (e.g. ["bandit_static_code"]).

    Returns
    -------
    list of Scenario
        In the deterministic order of the scenario table (not config order),
        so run ordering is identical across benchmark executions.
    """
    scenarios: List[Scenario] = []
    for key, (prefix, skill_name) in _SCENARIO_TABLE.items():
        if key not in enabled:
            continue
        intent_paths = sorted(_INTENTS_DIR.glob(f"{prefix}*.json"))
        if not intent_paths:
            raise FileNotFoundError(
                f"No intent files matching '{prefix}*.json' in {_INTENTS_DIR}"
            )
        intents = []
        for intent_path in intent_paths:
            with open(intent_path, encoding="utf-8") as fh:
                intents.append(_resolve_paths(json.load(fh)))
        tool_fn = skill_name.replace("-", "_")
        scenarios.append(
            Scenario(
                name=key,
                intents=tuple(intents),
                expected_skill=skill_name,
                expected_tool_fn=tool_fn,
                expected_agent=f"{tool_fn}_agent",
            )
        )
    return scenarios
