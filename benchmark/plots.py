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
- cpu_usage.png           average / peak CPU utilisation per cell (Ollama
                          server when sampled, harness process otherwise —
                          the figure title names the source)
- memory_usage.png        average / peak RSS per cell (same source rule)
- gpu_usage.png           average / peak GPU utilisation (when sampled)
- vram_usage.png          average / peak GPU memory (when sampled)
- token_usage.png         mean total tokens per cell
- throughput.png          requests-per-second vs concurrency (if measured)
"""

import argparse
import csv
import re
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

# In line plots (throughput), architecture is encoded by line STYLE and
# marker while each MODEL gets its own colour — otherwise several models of
# the same architecture would share an identical colour+style and be
# indistinguishable.
_ARCH_LINESTYLES = {"single_agent": "-", "multi_agent": "--"}
_ARCH_MARKERS = {"single_agent": "o", "multi_agent": "s"}


def _model_sort_key(model: str):
    """
    Sort models by parameter count when the tag ends in a size (e.g.
    'qwen3.5:0.8b' < 'qwen3.5:2b' < 'qwen3.5:27b'), falling back to
    alphabetical.  A plain string sort would order 27b between 0.8b and 2b.
    """
    match = re.search(r":(\d+(?:\.\d+)?)b\b", model)
    return (model.split(":")[0], float(match.group(1)) if match else 0.0, model)


def _model_colours(models) -> dict:
    """Assign each model a distinct colour from the tab10/tab20 palettes."""
    models = sorted(models, key=_model_sort_key)
    cmap = plt.get_cmap("tab10" if len(models) <= 10 else "tab20")
    return {m: cmap(i % cmap.N) for i, m in enumerate(models)}

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


def _load_rows(csv_path: Path, ok_only: bool = True) -> List[dict]:
    """Read the flat benchmark CSV; numeric fields stay strings here and are
    converted where used ('N/A' handled per metric).  ``ok_only`` keeps only
    successful runs (for latency/resource figures); pass False for routing
    metrics, which are recorded regardless of execution success."""
    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if r.get("status") == "OK"] if ok_only else rows


def _float(row: dict, key: str) -> Optional[float]:
    value = row.get(key, "")
    if value in ("", "N/A", None):
        return None
    return float(value)


def _has_data(rows: List[dict], key: str) -> bool:
    """True when at least one row carries a real value for this column."""
    return any(_float(row, key) is not None for row in rows)


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

    # CPU / memory figures prefer the Ollama SERVER metrics (where inference
    # happens); harness metrics are the fallback (e.g. dry-run data) and the
    # figure title always names the measured source.
    if _has_data(rows, "server_cpu_avg"):
        _resource_bars(rows, plots_dir,
                       metric_avg="server_cpu_avg", metric_peak="server_cpu_peak",
                       ylabel="CPU utilisation (%) — Ollama server",
                       filename="cpu_usage.png")
        _resource_bars(rows, plots_dir,
                       metric_avg="server_rss_avg_mb", metric_peak="server_rss_peak_mb",
                       ylabel="RSS memory (MB) — Ollama server",
                       filename="memory_usage.png")
    else:
        _resource_bars(rows, plots_dir, metric_avg="cpu_avg", metric_peak="cpu_peak",
                       ylabel="CPU utilisation (%) — harness process",
                       filename="cpu_usage.png")
        _resource_bars(rows, plots_dir, metric_avg="rss_avg_mb", metric_peak="rss_peak_mb",
                       ylabel="RSS memory (MB) — harness process",
                       filename="memory_usage.png")
    if _has_data(rows, "gpu_util_avg"):
        _resource_bars(rows, plots_dir,
                       metric_avg="gpu_util_avg", metric_peak="gpu_util_peak",
                       ylabel="GPU utilisation (%)", filename="gpu_usage.png")
        _resource_bars(rows, plots_dir,
                       metric_avg="vram_avg_mb", metric_peak="vram_peak_mb",
                       ylabel="GPU memory (MB)", filename="vram_usage.png")
    _token_bars(rows, plots_dir)

    # Routing metrics are recorded even for failed runs, so read all rows.
    _routing_decomposition(_load_rows(raw_dir / f"{run_id}.csv", ok_only=False),
                           plots_dir)

    tp_path = raw_dir / f"{run_id}_throughput.csv"
    if tp_path.exists() and tp_path.stat().st_size > 0:
        _throughput_lines(tp_path, plots_dir)

    print(f"plots: figures written to {plots_dir}")


def _latency_boxplot(rows: List[dict], plots_dir: Path) -> None:
    """End-to-end latency distribution per model, one box per architecture.

    Concurrency = 1 only, so the distribution reflects the architecture's
    isolated latency rather than queueing under load (see the throughput
    figure for behaviour under concurrency).
    """
    # data[model][architecture] = [latencies...]
    data: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row.get("concurrency") not in ("1", 1):
            continue
        value = _float(row, "e2e_ms")
        if value is not None:
            data[row["model"]][row["architecture"]].append(value)

    models = sorted(data, key=_model_sort_key)
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
    ax.set_title("End-to-end latency by model and architecture (concurrency = 1)")
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

    models = sorted(data, key=_model_sort_key)
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

    models = sorted(data, key=_model_sort_key)
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


def _routing_decomposition(rows: List[dict], plots_dir: Path) -> None:
    """
    Decision vs native-call adherence per model, averaged over the supported
    scenarios, one panel per architecture (concurrency = 1).  Shows that
    decision quality is uniform while native-call adherence is the axis of
    variation between models and architectures.
    """
    # data[arch][model] = {"decision": [...], "native": [...]}
    data: Dict[str, Dict[str, Dict[str, List[float]]]] = defaultdict(
        lambda: defaultdict(lambda: {"decision": [], "native": []}))
    for row in rows:
        if row.get("concurrency") not in ("1", 1):
            continue
        if row.get("scenario") == "unsupported_request":
            continue  # gatekeeping is a different axis; exclude here
        arch, model = row["architecture"], row["model"]
        data[arch][model]["decision"].append(1.0 if row.get("decision_correct") == "True" else 0.0)
        data[arch][model]["native"].append(1.0 if row.get("native_call") == "True" else 0.0)
    architectures = [a for a in ("single_agent", "multi_agent") if a in data]
    if not architectures:
        return
    models = sorted({m for a in data for m in data[a]}, key=_model_sort_key)

    fig, axes = plt.subplots(1, len(architectures),
                             figsize=(max(6, 2.2 * len(models)) * len(architectures) / 2, 4),
                             sharey=True, squeeze=False)
    width = 0.38
    for ax, arch in zip(axes[0], architectures):
        x = range(len(models))
        dec = [100 * (sum(v) / len(v)) if (v := data[arch][m]["decision"]) else 0
               for m in models]
        nat = [100 * (sum(v) / len(v)) if (v := data[arch][m]["native"]) else 0
               for m in models]
        ax.bar([i - width / 2 for i in x], dec, width, label="Decision",
               color="#1f77b4", alpha=0.85)
        ax.bar([i + width / 2 for i in x], nat, width, label="Native call",
               color="#d62728", alpha=0.85)
        ax.set_xticks(list(x))
        ax.set_xticklabels([_short_model(m) for m in models], rotation=20, ha="right")
        ax.set_title(_ARCH_LABELS.get(arch, arch))
        ax.set_ylim(0, 105)
    axes[0][0].set_ylabel("Supported-scenario accuracy (%)")
    axes[0][0].legend(fontsize=8)
    fig.suptitle("Routing decision vs native-call adherence (concurrency = 1)")
    fig.tight_layout()
    fig.savefig(plots_dir / "routing_decomposition.png")
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

    # Colour identifies the MODEL; linestyle + marker identify the
    # architecture — every line is unambiguous even with many models.
    colours = _model_colours({model for (_arch, model) in series})

    fig, ax = plt.subplots(figsize=(6, 4))
    for (arch, model), by_conc in sorted(
            series.items(), key=lambda kv: (kv[0][0], _model_sort_key(kv[0][1]))):
        concurrency = sorted(by_conc)
        rps = [sum(by_conc[c]) / len(by_conc[c]) for c in concurrency]
        ax.plot(concurrency, rps,
                color=colours[model],
                linestyle=_ARCH_LINESTYLES.get(arch, "-"),
                marker=_ARCH_MARKERS.get(arch, "o"),
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
