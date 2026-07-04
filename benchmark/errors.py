"""
Error summary — diagnose failed benchmark runs without eyeballing raw logs.

Reads the raw results JSON of a benchmark execution, groups the FAILED runs
by (model, architecture, scenario), and prints how often each distinct error
occurred.  Use it after any campaign with unexpected failures:

    python -m benchmark.errors --experiment family_comparison
    python -m benchmark.errors --experiment scaling_study --run-id <run_id>

Typical output::

    ollama_chat/gemma3:4b | single_agent | bandit_static_code   30 failed / 30
      30x  APIConnectionError: ... does not support tools ...

Reading the counts side by side with the routing column usually classifies
a failure immediately: server rejections are uniform and fast, model
protocol failures are varied, framework bugs are uniform AND unexpected.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark.config import load_config  # noqa: E402

# How much of each distinct error message to show.
_ERROR_WIDTH = 160


def _latest_run_id(raw_dir: Path) -> Optional[str]:
    """Most recently modified <run_id>.json in the raw directory."""
    candidates = sorted(raw_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    return candidates[-1].stem if candidates else None


def _normalise(error: Optional[str]) -> str:
    """First line of the error, truncated — enough to identify the cause."""
    if not error:
        return "(no error message recorded)"
    first_line = error.strip().splitlines()[0]
    if len(first_line) > _ERROR_WIDTH:
        first_line = first_line[:_ERROR_WIDTH] + "…"
    return first_line


def summarize_errors(experiment: str, run_id: Optional[str], cfg) -> None:
    """Print the per-cell error breakdown of one benchmark execution."""
    raw_dir = cfg.results_dir / experiment / "raw"
    if run_id is None:
        run_id = _latest_run_id(raw_dir)
    if run_id is None:
        print(f"errors: no raw JSON found in {raw_dir}")
        return

    with open(raw_dir / f"{run_id}.json", encoding="utf-8") as fh:
        data = json.load(fh)

    # cell -> (total runs, Counter of error messages, routing-ok-but-failed count)
    cells = defaultdict(lambda: {"total": 0, "failed": 0,
                                 "errors": Counter(), "routing_ok_failed": 0})
    for run in data.get("runs", []):
        if run.get("warmup"):
            continue
        key = (run["model"], run["architecture"], run["scenario"])
        cell = cells[key]
        cell["total"] += 1
        if run.get("status") != "OK":
            cell["failed"] += 1
            cell["errors"][_normalise(run.get("error"))] += 1
            if run.get("routing_correct"):
                cell["routing_ok_failed"] += 1

    print(f"Run: {run_id}\n")
    any_failures = False
    for (model, arch, scenario), cell in sorted(cells.items()):
        if cell["failed"] == 0:
            continue
        any_failures = True
        print(f"{model} | {arch} | {scenario}   "
              f"{cell['failed']} failed / {cell['total']}")
        if cell["routing_ok_failed"]:
            print(f"      (routing was CORRECT in {cell['routing_ok_failed']} "
                  f"of the failed runs — failure happened after selection)")
        for message, count in cell["errors"].most_common():
            print(f"  {count:3d}x  {message}")
        print()
    if not any_failures:
        print("No failed measured runs in this execution.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarise benchmark run errors")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--run-id", default=None,
                        help="specific run ID (default: most recent)")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)
    summarize_errors(args.experiment, args.run_id, cfg)


if __name__ == "__main__":
    main()
