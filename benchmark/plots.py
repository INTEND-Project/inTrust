"""
Figure generation — completely separate from the benchmark runner.

Reads the raw CSV files written by ``report_writer.py`` and produces
publication-quality matplotlib figures in ``results/<experiment>/plots/``.
Because only stored data is read, figures can be regenerated (or restyled)
at any time without re-running any benchmark:

    python -m benchmark.plots --experiment family_comparison
    python -m benchmark.plots --experiment scaling_study --run-id <run_id>

Figures produced:
- latency_boxplot.png     end-to-end latency per model, grouped by architecture
- cpu_usage.png           average / peak CPU utilisation per cell
- memory_usage.png        average / peak RSS per cell
- token_usage.png         mean total tokens per cell
- throughput.png          requests-per-second vs concurrency (if measured)
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib

matplotlib.use("Agg")  # headless backend: never needs a display
import matplotlib.pyplot as plt  # noqa: E402

# Allow running as a plain script too.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark.config import BenchmarkConfig, load_config  # noqa: E402

# Consistent colours for the two architectures across all figures.
_ARCH_COLOURS = {"single_agent": "#1f77b4", "multi_agent": "#d62728"}
_ARCH_LABELS = {"single_agent": "Single agent + skills", "multi_agent": "Multi-agent"}

# Publication-quality defaults.
plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 300,
    "font.size": 9,
    "axes.grid": True,
    "grid.alpha": 0.3,
})


def _short_model(model: str) -> str:
    """'ollama_chat/qwen3:8b' -> 'qwen3:8b' (axis labels stay readable)."""
    return model.split("/")[-1]


def _latest_run_id(raw_dir: Path) -> Optional[str]:
    """Most recently modified <run_id>.csv in the raw directory."""
    candidates = sorted(
        (p for p in raw_dir.glob("*.csv") if not p.stem.endswith("_throughput")),
        key=lambda p: p.stat().st_mtime,
    )
    return candidates[-1].stem if candidates else None


def _load_rows(csv_path: Path) -> List[dict]:
    """Read the flat benchmark CSV; numeric fields stay strings here and are
    converted where used ('N/A' handled per metric)."""
    with open(csv_path, newline="", encoding="utf-8") as fh:
        return [row for row in csv.DictReader(fh) if row.get("status") == "OK"]


def _float(row: dict, key: str) -> Optional[float]:
    value = row.get(key, "")
    if value in ("", "N/A", None):
        return None
    return float(value)


def generate(experiment: str, run_id: Optional[str], cfg: BenchmarkConfig) -> None:
    """Generate all figures for one experiment's stored raw data."""
    raw_dir = cfg.results_dir / experiment / "raw"
    plots_dir = cfg.results_dir / experiment / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    if run_id is None:
        run_id = _latest_run_id(raw_dir)
    if run_id is None:
        print(f"plots: no raw CSV found in {raw_dir} — nothing to plot")
        return

    rows = _load_rows(raw_dir / f"{run_id}.csv")
    if not rows:
        print(f"plots: {run_id}.csv contains no successful runs — nothing to plot")
        return

    _latency_boxplot(rows, plots_dir)
    _resource_bars(rows, plots_dir, metric_avg="cpu_avg", metric_peak="cpu_peak",
                   ylabel="CPU utilisation (%)", filename="cpu_usage.png")
    _resource_bars(rows, plots_dir, metric_avg="rss_avg_mb", metric_peak="rss_peak_mb",
                   ylabel="RSS memory (MB)", filename="memory_usage.png")
    _token_bars(rows, plots_dir)

    tp_path = raw_dir / f"{run_id}_throughput.csv"
    if tp_path.exists() and tp_path.stat().st_size > 0:
        _throughput_lines(tp_path, plots_dir)

    print(f"plots: figures written to {plots_dir}")


def _latency_boxplot(rows: List[dict], plots_dir: Path) -> None:
    """End-to-end latency distribution per model, one box per architecture."""
    # data[model][architecture] = [latencies...]
    data: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        value = _float(row, "e2e_ms")
        if value is not None:
            data[row["model"]][row["architecture"]].append(value)

    models = sorted(data)
    architectures = [a for a in ("single_agent", "multi_agent")
                     if any(a in d for d in data.values())]

    fig, ax = plt.subplots(figsize=(max(6, 1.6 * len(models)), 4))
    width = 0.35
    for k, arch in enumerate(architectures):
        positions = [i + (k - (len(architectures) - 1) / 2) * width
                     for i in range(len(models))]
        values = [data[m].get(arch, []) for m in models]
        boxes = ax.boxplot(
            values, positions=positions, widths=width * 0.9,
            patch_artist=True, showfliers=True,
            medianprops={"color": "black"},
        )
        for patch in boxes["boxes"]:
            patch.set_facecolor(_ARCH_COLOURS[arch])
            patch.set_alpha(0.7)
    ax.set_xticks(range(len(models)))
    ax.set_xticklabels([_short_model(m) for m in models], rotation=20, ha="right")
    ax.set_ylabel("End-to-end latency (ms)")
    ax.set_title("End-to-end latency by model and architecture")
    handles = [plt.Rectangle((0, 0), 1, 1, fc=_ARCH_COLOURS[a], alpha=0.7)
               for a in architectures]
    ax.legend(handles, [_ARCH_LABELS[a] for a in architectures])
    fig.tight_layout()
    fig.savefig(plots_dir / "latency_boxplot.png")
    plt.close(fig)


def _resource_bars(rows: List[dict], plots_dir: Path, metric_avg: str,
                   metric_peak: str, ylabel: str, filename: str) -> None:
    """Grouped bars: mean of the avg metric (solid) + mean peak (hatched)."""
    data: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    peaks: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        avg, peak = _float(row, metric_avg), _float(row, metric_peak)
        if avg is not None:
            data[row["model"]][row["architecture"]].append(avg)
        if peak is not None:
            peaks[row["model"]][row["architecture"]].append(peak)

    models = sorted(data)
    architectures = [a for a in ("single_agent", "multi_agent")
                     if any(a in d for d in data.values())]

    fig, ax = plt.subplots(figsize=(max(6, 1.6 * len(models)), 4))
    width = 0.35
    for k, arch in enumerate(architectures):
        offsets = [i + (k - (len(architectures) - 1) / 2) * width
                   for i in range(len(models))]
        means = [sum(v) / len(v) if (v := data[m].get(arch, [])) else 0
                 for m in models]
        peak_means = [sum(v) / len(v) if (v := peaks[m].get(arch, [])) else 0
                      for m in models]
        ax.bar(offsets, means, width * 0.9, color=_ARCH_COLOURS[arch], alpha=0.8,
               label=f"{_ARCH_LABELS[arch]} (avg)")
        ax.bar(offsets, [p - m for p, m in zip(peak_means, means)], width * 0.9,
               bottom=means, color=_ARCH_COLOURS[arch], alpha=0.35, hatch="//",
               label=f"{_ARCH_LABELS[arch]} (peak)")
    ax.set_xticks(range(len(models)))
    ax.set_xticklabels([_short_model(m) for m in models], rotation=20, ha="right")
    ax.set_ylabel(ylabel)
    ax.set_title(ylabel)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(plots_dir / filename)
    plt.close(fig)


def _token_bars(rows: List[dict], plots_dir: Path) -> None:
    """Mean total token consumption per model and architecture."""
    data: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        value = _float(row, "total_tokens")
        if value is not None:
            data[row["model"]][row["architecture"]].append(value)
    if not data:
        print("plots: no token data available (backend reported N/A) — "
              "skipping token_usage.png")
        return

    models = sorted(data)
    architectures = [a for a in ("single_agent", "multi_agent")
                     if any(a in d for d in data.values())]

    fig, ax = plt.subplots(figsize=(max(6, 1.6 * len(models)), 4))
    width = 0.35
    for k, arch in enumerate(architectures):
        offsets = [i + (k - (len(architectures) - 1) / 2) * width
                   for i in range(len(models))]
        means = [sum(v) / len(v) if (v := data[m].get(arch, [])) else 0
                 for m in models]
        ax.bar(offsets, means, width * 0.9, color=_ARCH_COLOURS[arch], alpha=0.8,
               label=_ARCH_LABELS[arch])
    ax.set_xticks(range(len(models)))
    ax.set_xticklabels([_short_model(m) for m in models], rotation=20, ha="right")
    ax.set_ylabel("Mean total tokens per run")
    ax.set_title("Token consumption by model and architecture")
    ax.legend()
    fig.tight_layout()
    fig.savefig(plots_dir / "token_usage.png")
    plt.close(fig)


def _throughput_lines(tp_path: Path, plots_dir: Path) -> None:
    """Requests-per-second vs concurrency, one line per (arch, model)."""
    with open(tp_path, newline="", encoding="utf-8") as fh:
        records = list(csv.DictReader(fh))
    if not records:
        return

    # series[(arch, model)] = [(concurrency, rps), ...] averaged over scenarios
    series: Dict[tuple, Dict[int, List[float]]] = defaultdict(lambda: defaultdict(list))
    for rec in records:
        key = (rec["architecture"], rec["model"])
        series[key][int(rec["concurrency"])].append(float(rec["rps"]))

    fig, ax = plt.subplots(figsize=(6, 4))
    for (arch, model), by_conc in sorted(series.items()):
        concurrency = sorted(by_conc)
        rps = [sum(by_conc[c]) / len(by_conc[c]) for c in concurrency]
        ax.plot(concurrency, rps, marker="o",
                color=_ARCH_COLOURS.get(arch),
                linestyle="-" if arch == "single_agent" else "--",
                label=f"{_ARCH_LABELS.get(arch, arch)} / {_short_model(model)}")
    ax.set_xlabel("Concurrency level")
    ax.set_ylabel("Requests per second")
    ax.set_title("Throughput vs concurrency")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(plots_dir / "throughput.png")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate benchmark figures")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--run-id", default=None,
                        help="specific run ID (default: most recent)")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)
    generate(args.experiment, args.run_id, cfg)


if __name__ == "__main__":
    main()
