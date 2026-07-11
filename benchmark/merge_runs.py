"""
Merge the results of several benchmark executions into one result set.

Long campaigns are split across chained Slurm jobs (each part runs a subset
of the experiment's models — see benchmark/slurm/submit_split_campaign.sh);
this tool combines the parts afterwards:

    python -m benchmark.merge_runs --experiment scaling_study \
        --run-ids scaling_study_20260710-..._ab12cd34 scaling_study_20260711-..._ef56ab78

The merged result is written as a NEW execution (run id
``<experiment>_merged_<stamp>_<hash>``) with the full set of outputs — raw
JSON/CSV, throughput CSV, JSONL log, summary.md — and freshly generated
plots and LaTeX tables.  The part files are never modified: a merged run is
just another run id, reproducible from its parts at any time.

Parts are expected to PARTITION the experiment's models: if two parts
contain the same (model, architecture, scenario) cell, its statistics would
be double-counted, so the tool warns loudly.
"""

import argparse
import dataclasses
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark import latex_tables, plots  # noqa: E402
from benchmark.config import load_config  # noqa: E402
from benchmark.metrics import RunResult  # noqa: E402
from benchmark.report_writer import write_outputs  # noqa: E402

# Only known dataclass fields are taken from stored run dicts, so merging
# stays robust when older parts predate newly added RunResult fields.
_RUN_FIELDS = {f.name for f in dataclasses.fields(RunResult)}


def merge(experiment: str, run_ids: List[str], cfg) -> str:
    """Merge the given executions and return the new merged run id."""
    raw_dir = cfg.results_dir / experiment / "raw"

    results: List[RunResult] = []
    throughput: List[dict] = []
    # cell -> set of part run_ids that contain it (for overlap detection).
    cell_sources: dict = {}
    for run_id in run_ids:
        path = raw_dir / f"{run_id}.json"
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        part_runs = [
            RunResult(**{k: v for k, v in run.items() if k in _RUN_FIELDS})
            for run in data.get("runs", [])
        ]
        results.extend(part_runs)
        throughput.extend(data.get("throughput", []))
        for r in part_runs:
            if not r.warmup:
                key = (r.model, r.architecture, r.scenario)
                cell_sources.setdefault(key, set()).add(run_id)
        print(f"loaded {run_id}: {len(part_runs)} runs, "
              f"{len(data.get('throughput', []))} throughput records")

    # Detect double-counted cells: the parts should partition the models.
    overlaps = {key: ids for key, ids in cell_sources.items() if len(ids) > 1}
    if overlaps:
        print("\nWARNING: the same cell appears in MULTIPLE parts — its "
              "statistics will be double-counted in the merged outputs:")
        for (model, arch, scen), ids in sorted(overlaps.items()):
            print(f"  {model} | {arch} | {scen}  <- {', '.join(sorted(ids))}")
        print("Parts should partition the experiment's models.\n")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    merged_id = f"{experiment}_merged_{stamp}_{uuid.uuid4().hex[:8]}"

    paths = write_outputs(experiment, merged_id, cfg, results, throughput)
    print("Merged outputs written:")
    for kind, path in paths.items():
        print(f"  {kind:15s} {path}")

    plots.generate(experiment, merged_id, cfg)
    latex_tables.generate(experiment, merged_id, cfg)
    return merged_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge several benchmark executions into one result set")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--run-ids", nargs="+", required=True,
                        help="two or more run IDs of the parts to merge")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    if len(args.run_ids) < 2:
        parser.error("--run-ids needs at least two run IDs")
    if len(set(args.run_ids)) != len(args.run_ids):
        parser.error("--run-ids contains a duplicate run ID (each part must "
                     "be listed once, otherwise its runs are double-counted)")
    cfg = load_config(args.config)
    merged_id = merge(args.experiment, args.run_ids, cfg)
    print(f"\nMerged run id: {merged_id}")


if __name__ == "__main__":
    main()
