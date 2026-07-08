"""
Benchmark output writer.

Produces, for every benchmark execution (identified by a unique run ID):

- ``results/<experiment>/raw/<run_id>.json``  — full per-run records,
  including the raw event timelines (for deep post-hoc analysis).
- ``results/<experiment>/raw/<run_id>.csv``   — one row per MEASURED run,
  flat columns, directly usable by plotting tools.
- ``results/<experiment>/raw/<run_id>_throughput.csv`` — one row per
  (architecture, model, scenario, concurrency) throughput cell.
- ``results/logs/<run_id>.jsonl``             — structured execution log.
- ``results/<experiment>/summary.md``         — human-readable statistical
  summary of the latest execution (config echo + stats tables).

Plots and LaTeX tables are generated separately (``plots.py`` /
``latex_tables.py``) from the CSV/JSON files, so they can be regenerated at
any time without re-running the benchmark.
"""

import csv
import dataclasses
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .config import BenchmarkConfig
from .metrics import RunResult, summarize

# CSV columns, in the exact order they appear in the file.
_CSV_COLUMNS = [
    "architecture", "model", "scenario", "concurrency", "run_idx",
    "intent_variant",
    "e2e_ms", "selection_ms", "llm_ms", "tool_ms", "format_ms",
    "cpu_avg", "cpu_peak", "rss_avg_mb", "rss_peak_mb",
    "prompt_tokens", "completion_tokens", "total_tokens",
    "routing_correct", "status",
]


def new_run_id(experiment_name: str) -> str:
    """Unique identifier for one benchmark execution."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{experiment_name}_{stamp}_{uuid.uuid4().hex[:8]}"


def _na(value: Any) -> Any:
    """Render missing values as 'N/A' (e.g. unavailable token statistics)."""
    return "N/A" if value is None else value


def write_outputs(
    experiment_name: str,
    run_id: str,
    cfg: BenchmarkConfig,
    results: List[RunResult],
    throughput: List[Dict[str, Any]],
) -> Dict[str, Path]:
    """
    Write all output files for one benchmark execution.

    Returns a dict of the paths written (for the CLI to print).
    """
    exp_dir = cfg.results_dir / experiment_name
    raw_dir = exp_dir / "raw"
    logs_dir = cfg.results_dir / "logs"
    for d in (raw_dir, exp_dir / "plots", exp_dir / "latex", logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    measured = [r for r in results if not r.warmup]

    # ---- raw JSON: everything, warm-ups included ------------------------------
    json_path = raw_dir / f"{run_id}.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "run_id": run_id,
                "experiment": experiment_name,
                "written_at": datetime.now().isoformat(),
                "config": _config_echo(cfg),
                "runs": [r.to_dict() for r in results],
                "throughput": throughput,
            },
            fh, indent=2,
        )

    # ---- flat CSV: measured runs only, plot-ready ------------------------------
    csv_path = raw_dir / f"{run_id}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for r in measured:
            row = {col: _na(getattr(r, col)) for col in _CSV_COLUMNS}
            writer.writerow(row)

    # ---- throughput CSV ----------------------------------------------------------
    tp_path = raw_dir / f"{run_id}_throughput.csv"
    with open(tp_path, "w", newline="", encoding="utf-8") as fh:
        if throughput:
            writer = csv.DictWriter(fh, fieldnames=list(throughput[0].keys()))
            writer.writeheader()
            writer.writerows(throughput)

    # ---- structured JSONL log ------------------------------------------------------
    log_path = logs_dir / f"{run_id}.jsonl"
    with open(log_path, "w", encoding="utf-8") as fh:
        for r in results:
            entry = r.to_dict()
            entry.pop("timeline", None)   # keep the log compact
            entry.pop("final_text", None)
            entry["run_id"] = run_id
            entry["logged_at"] = time.time()
            fh.write(json.dumps(entry) + "\n")

    # ---- Markdown summary ------------------------------------------------------------
    md_path = exp_dir / "summary.md"
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(_summary_markdown(experiment_name, run_id, cfg, measured, throughput))

    return {"json": json_path, "csv": csv_path, "throughput_csv": tp_path,
            "log": log_path, "summary": md_path}


def _config_echo(cfg: BenchmarkConfig) -> Dict[str, Any]:
    """Serialisable snapshot of the configuration used for this execution."""
    echo = dataclasses.asdict(cfg)
    echo["results_dir"] = str(cfg.results_dir)
    echo.pop("extra", None)
    return echo


def _summary_markdown(
    experiment_name: str,
    run_id: str,
    cfg: BenchmarkConfig,
    measured: List[RunResult],
    throughput: List[Dict[str, Any]],
) -> str:
    """Build the human-readable summary.md content."""
    lines: List[str] = []
    lines.append(f"# Benchmark summary — {experiment_name}")
    lines.append("")
    lines.append(f"- Run ID: `{run_id}`")
    lines.append(f"- Generated: {datetime.now().isoformat()}")
    lines.append(f"- Warm-up runs (excluded): {cfg.warmup_runs}")
    lines.append(f"- Measured runs per cell: {cfg.measured_runs}")
    lines.append(f"- Seed: {cfg.seed}")
    lines.append(f"- Scenarios: {', '.join(cfg.enabled_scenarios)}")
    lines.append("")

    # Group measured runs per (architecture, model, scenario) cell.
    cells: Dict[tuple, List[RunResult]] = {}
    for r in measured:
        cells.setdefault((r.architecture, r.model, r.scenario), []).append(r)

    lines.append("## Latency and routing per cell")
    lines.append("")
    lines.append("| Architecture | Model | Scenario | n | Mean (ms) | Median | Stdev | p95 | Min | Max | Routing acc. | Failures |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for (arch, model, scen), runs in sorted(cells.items()):
        ok = [r for r in runs if r.status == "OK"]
        stats = summarize([r.e2e_ms for r in ok])
        acc = (sum(r.routing_correct for r in runs) / len(runs)) * 100.0
        lines.append(
            f"| {arch} | {model} | {scen} | {len(runs)} "
            f"| {stats['mean']:.0f} | {stats['median']:.0f} "
            f"| {stats['stdev']:.0f} | {stats['p95']:.0f} "
            f"| {stats['min']:.0f} | {stats['max']:.0f} "
            f"| {acc:.0f}% | {len(runs) - len(ok)} |"
        )
    lines.append("")

    lines.append("## Resource usage per cell (process-wide)")
    lines.append("")
    lines.append("| Architecture | Model | Scenario | CPU avg (%) | CPU peak (%) | RSS avg (MB) | RSS peak (MB) | Tokens (mean total) |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for (arch, model, scen), runs in sorted(cells.items()):
        ok = [r for r in runs if r.status == "OK"]
        if not ok:
            continue
        tokens = [r.total_tokens for r in ok if r.total_tokens is not None]
        token_str = f"{sum(tokens) / len(tokens):.0f}" if tokens else "N/A"
        lines.append(
            f"| {arch} | {model} | {scen} "
            f"| {sum(r.cpu_avg for r in ok) / len(ok):.1f} "
            f"| {max(r.cpu_peak for r in ok):.1f} "
            f"| {sum(r.rss_avg_mb for r in ok) / len(ok):.0f} "
            f"| {max(r.rss_peak_mb for r in ok):.0f} "
            f"| {token_str} |"
        )
    lines.append("")

    if throughput:
        lines.append("## Throughput")
        lines.append("")
        lines.append("| Architecture | Model | Scenario | Concurrency | Req/s | Avg latency (ms) | Failures |")
        lines.append("|---|---|---|---|---|---|---|")
        for t in throughput:
            lines.append(
                f"| {t['architecture']} | {t['model']} | {t['scenario']} "
                f"| {t['concurrency']} | {t['rps']:.3f} "
                f"| {t['avg_latency_ms']:.0f} | {t['failures']} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("Regenerate figures:  `python -m benchmark.plots --experiment "
                 f"{experiment_name}`")
    lines.append("Regenerate tables:   `python -m benchmark.latex_tables --experiment "
                 f"{experiment_name}`")
    lines.append("")
    return "\n".join(lines)
