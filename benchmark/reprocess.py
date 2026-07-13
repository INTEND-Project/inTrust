"""
Reprocess a stored benchmark run — recompute derived metrics from the raw
records without re-running the experiment.

The routing decomposition (decision vs native-call adherence, corrected
gatekeeping — see routing_analysis.py) is computed from each run's
``selected`` and ``final_text``, both of which are already stored.  This
tool backfills those fields on an existing raw JSON and regenerates all
outputs (CSV, summary, plots, LaTeX) under a new run id, so results from
before the decomposition existed can be analysed without any GPU time.

    python -m benchmark.reprocess --experiment family_comparison --run-id <id>

The original files are never modified; the reprocessed run is a new id.
"""

import argparse
import dataclasses
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark import latex_tables, plots, routing_analysis  # noqa: E402
from benchmark.config import load_config  # noqa: E402
from benchmark.metrics import RunResult  # noqa: E402
from benchmark.report_writer import write_outputs  # noqa: E402
from benchmark.scenarios import _SCENARIO_TABLE  # noqa: E402

_RUN_FIELDS = {f.name for f in dataclasses.fields(RunResult)}

# scenario key -> (expected_skill, is_supported); mirrors scenarios.load_scenarios.
_SCEN_META = {
    key: (skill, skill is not None)
    for key, (_prefix, skill) in _SCENARIO_TABLE.items()
}


def _backfill_decomposition(run: RunResult) -> None:
    """Fill intended_skill / native_call / decision_correct from stored fields."""
    intended, native_call, refused = routing_analysis.classify(
        run.selected, run.final_text)
    expected_skill, is_supported = _SCEN_META.get(run.scenario, (None, True))
    run.intended_skill = intended
    run.native_call = native_call
    run.decision_correct = routing_analysis.decision_correct(
        intended, native_call, refused, expected_skill, is_supported)


def reprocess(experiment: str, run_id: str, cfg) -> str:
    raw_dir = cfg.results_dir / experiment / "raw"
    with open(raw_dir / f"{run_id}.json", encoding="utf-8") as fh:
        data = json.load(fh)

    results: List[RunResult] = []
    for run in data.get("runs", []):
        r = RunResult(**{k: v for k, v in run.items() if k in _RUN_FIELDS})
        _backfill_decomposition(r)
        results.append(r)
    throughput: List[Dict] = data.get("throughput", [])
    print(f"reprocessed {len(results)} runs from {run_id}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    new_id = f"{experiment}_reprocessed_{stamp}"
    paths = write_outputs(experiment, new_id, cfg, results, throughput)
    for kind, path in paths.items():
        print(f"  {kind:15s} {path}")
    plots.generate(experiment, new_id, cfg)
    latex_tables.generate(experiment, new_id, cfg)
    return new_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recompute derived metrics for a stored run (no re-run)")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)
    new_id = reprocess(args.experiment, args.run_id, cfg)
    print(f"\nReprocessed run id: {new_id}")


if __name__ == "__main__":
    main()
