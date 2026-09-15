"""
Re-score the routing decomposition of stored benchmark executions.

The decomposition (``routing_analysis``) separates the routing DECISION from
native-call ADHERENCE.  It was later extended to recognise one more failure
mode of the multi-agent root: calling the specialist's name as if it were a
tool (e.g. ``trivy_filesystem_agent(...)``) instead of the hand-off function.
The framework rejects such a call, so the run fails and ``selected`` is empty
— but the call name, kept in the stored event timeline, still identifies the
capability the model chose.

This tool recomputes ``intended_skill``, ``native_call`` and
``decision_correct`` for existing raw results from their stored ``selected``,
``final_text`` and ``timeline`` — no re-runs.  ``routing_correct`` (native call
to the expected target) is never changed.

    # Report what would change, writing nothing:
    python -m benchmark.rescore_runs --experiment pilot_32 \\
        --config benchmark/config.registry_sweep.toml \\
        --run-ids pilot_32_20260915-112228_0ecbcade --check

    # Write the re-scored execution as a NEW run id (originals untouched):
    python -m benchmark.rescore_runs --experiment pilot_32 \\
        --config benchmark/config.registry_sweep.toml \\
        --run-ids pilot_32_20260915-112228_0ecbcade

Pass the same ``--config`` the runs were produced with: write mode echoes it
into the new outputs and resolves ``results_dir`` from it.
"""

import argparse
import dataclasses
import json
import sys
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark import latex_tables, plots, routing_analysis  # noqa: E402
from benchmark.config import load_config  # noqa: E402
from benchmark.distractors import make_distractor_skills  # noqa: E402
from benchmark.metrics import RunResult  # noqa: E402
from benchmark.report_writer import write_outputs  # noqa: E402
from benchmark.scenarios import _SCENARIO_TABLE  # noqa: E402

_RUN_FIELDS = {f.name for f in dataclasses.fields(RunResult)}
_TRANSFER_FN = "transfer_to_agent"
_ROOT_AGENT = "orchestrator"


def attempted_call_from_timeline(run: RunResult) -> Optional[str]:
    """First non-hand-off call by the multi-agent root when nothing was selected."""
    if run.architecture != "multi_agent" or run.selected is not None:
        return None
    for event in run.timeline or []:
        if (event.get("kind") == "function_call"
                and event.get("author") == _ROOT_AGENT
                and event.get("name") != _TRANSFER_FN):
            return event.get("name")
    return None


def rescore_run(run: RunResult) -> RunResult:
    """Return ``run`` with its routing decomposition recomputed."""
    expected_skill = _SCENARIO_TABLE[run.scenario][1]
    attempted = run.attempted_call or attempted_call_from_timeline(run)
    intended, native_call, refused = routing_analysis.classify(
        run.selected, run.final_text, attempted)
    decision = routing_analysis.decision_correct(
        intended, native_call, refused, expected_skill,
        is_supported=expected_skill is not None)
    return dataclasses.replace(
        run, attempted_call=attempted, intended_skill=intended,
        native_call=native_call, decision_correct=decision)


def _load(path: Path, experiment: str) -> Tuple[dict, List[RunResult]]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    # Register synthetic distractor names so decisions naming them resolve.
    echoed = ((data.get("config") or {}).get("experiments") or {}).get(experiment) or {}
    make_distractor_skills(int(echoed.get("extra_distractor_skills", 0) or 0))
    runs = [RunResult(**{k: v for k, v in r.items() if k in _RUN_FIELDS})
            for r in data.get("runs", [])]
    return data, runs


def _cell_table(before: List[RunResult], after: List[RunResult]) -> None:
    """Print decision/native accuracy per cell where anything changed."""
    cells = defaultdict(lambda: [0, 0, 0, 0, 0])  # n, dec_b, dec_a, nat_b, nat_a
    for b, a in zip(before, after):
        if b.warmup:
            continue
        c = cells[(b.model.split("/")[-1], b.architecture, b.scenario)]
        c[0] += 1
        c[1] += b.decision_correct
        c[2] += a.decision_correct
        c[3] += b.native_call
        c[4] += a.native_call
    shown = False
    for (model, arch, scen), (n, db, da, nb, na) in sorted(cells.items()):
        if db != da or nb != na:
            if not shown:
                print(f"  {'model':<24}{'architecture':<14}{'scenario':<21}"
                      f"{'decision %':>14}{'native %':>12}")
                shown = True
            print(f"  {model:<24}{arch:<14}{scen:<21}"
                  f"{100 * db / n:>6.0f} -> {100 * da / n:<5.0f}"
                  f"{100 * nb / n:>5.0f} -> {100 * na / n:<4.0f}")
    if not shown:
        print("  no cell changed")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-score the routing decomposition of stored runs")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--run-ids", nargs="+", required=True)
    parser.add_argument("--config", type=Path, default=None,
                        help="config the runs were produced with")
    parser.add_argument("--check", action="store_true",
                        help="report changes only; write nothing")
    args = parser.parse_args()
    cfg = load_config(args.config)
    raw_dir = cfg.results_dir / args.experiment / "raw"

    for run_id in args.run_ids:
        data, before = _load(raw_dir / f"{run_id}.json", args.experiment)
        after = [rescore_run(r) for r in before]
        changed = sum(
            (b.intended_skill, b.native_call, b.decision_correct)
            != (a.intended_skill, a.native_call, a.decision_correct)
            for b, a in zip(before, after) if not b.warmup)
        print(f"\n{run_id}: {changed} measured run(s) re-scored")
        _cell_table(before, after)
        if args.check:
            continue

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        new_id = f"{args.experiment}_rescored_{stamp}_{uuid.uuid4().hex[:8]}"
        paths = write_outputs(args.experiment, new_id, cfg, after,
                              data.get("throughput", []))
        print("  outputs written:")
        for kind, path in paths.items():
            print(f"    {kind:15s} {path}")
        plots.generate(args.experiment, new_id, cfg)
        latex_tables.generate(args.experiment, new_id, cfg)
        print(f"  re-scored run id: {new_id}")


if __name__ == "__main__":
    main()
