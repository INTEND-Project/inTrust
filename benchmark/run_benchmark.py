"""
Benchmark CLI — the single entry point for all experiments.

Usage examples (run from the repository root):

    # Run every experiment defined in the config:
    python -m benchmark.run_benchmark

    # Run one experiment:
    python -m benchmark.run_benchmark --experiment family_comparison

    # Quick verification with one model, one scenario, one run:
    python -m benchmark.run_benchmark --experiment family_comparison \\
        --model ollama_chat/qwen3:4b --scenario bandit_static_code \\
        --runs 1 --warmup 0

    # Test the whole pipeline (stats, CSV, summaries, plots, LaTeX)
    # WITHOUT a running Ollama server:
    python -m benchmark.run_benchmark --dry-run

After a benchmark finishes, figures and LaTeX tables are generated
automatically; they can also be regenerated at any time from the stored raw
data with ``python -m benchmark.plots`` / ``python -m benchmark.latex_tables``.
"""

import argparse
import asyncio
import dataclasses
import logging
import random
import sys
import warnings
from pathlib import Path

# Allow running both as a module (python -m benchmark.run_benchmark) and as a
# plain script (python benchmark/run_benchmark.py): put the repo root on
# sys.path so 'orchestrator', 'skills', 'tools' and 'benchmark' import cleanly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark import latex_tables, plots  # noqa: E402
from benchmark.config import BenchmarkConfig, load_config  # noqa: E402
from benchmark.experiment import run_experiment  # noqa: E402
from benchmark.metrics import RunResult  # noqa: E402
from benchmark.report_writer import new_run_id, write_outputs  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="InTrust ADK architecture benchmark",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", type=Path, default=None,
                        help="path to a TOML config (default: config.default.toml)")
    parser.add_argument("--experiment", default=None,
                        help="run only this experiment (default: all)")
    parser.add_argument("--model", action="append", default=None,
                        help="restrict to this model string; repeat the flag "
                             "to run a subset of the experiment's models "
                             "(used to split long campaigns across jobs)")
    parser.add_argument("--scenario", default=None,
                        help="restrict to one scenario key")
    parser.add_argument("--runs", type=int, default=None,
                        help="override measured_runs")
    parser.add_argument("--warmup", type=int, default=None,
                        help="override warmup_runs")
    parser.add_argument("--dry-run", action="store_true",
                        help="stub the LLM runs; exercises the full reporting "
                             "pipeline without Ollama")
    return parser.parse_args()


def _apply_overrides(cfg: BenchmarkConfig, args: argparse.Namespace) -> BenchmarkConfig:
    """Apply CLI overrides to the (frozen) config via dataclasses.replace."""
    changes = {}
    if args.runs is not None:
        changes["measured_runs"] = args.runs
    if args.warmup is not None:
        changes["warmup_runs"] = args.warmup
    if args.scenario is not None:
        # Explicit selection also works for scenarios disabled in the config.
        changes["enabled_scenarios"] = [args.scenario]
    if args.model is not None:
        # args.model is a list (action="append"): one entry per --model flag.
        experiments = {
            name: dataclasses.replace(exp, models=list(args.model))
            for name, exp in cfg.experiments.items()
        }
        changes["experiments"] = experiments
    return dataclasses.replace(cfg, **changes) if changes else cfg


async def _dry_run_execute(architecture, model_string, scenario, skills, cfg,
                           run_idx, concurrency=1, warmup=False) -> RunResult:
    """
    Dry-run stub: builds the real agent (validating all wiring: skills,
    tools, prompts, model factory) but skips the LLM call, returning
    plausible synthetic metrics so the reporting pipeline can be tested.
    """
    from benchmark.arch_multi import build_multi_agent
    from benchmark.arch_single import build_single_agent
    from benchmark.instrumentation import RunCollector

    collector = RunCollector()
    # Building the agent exercises skill loading, tool schemas, prompt
    # formatting and the model factory — everything except the network call.
    if architecture == "single_agent":
        build_single_agent(skills, model_string, cfg, collector)
        expected = scenario.expected_tool_fn
    else:
        build_multi_agent(skills, model_string, cfg, collector)
        expected = scenario.expected_agent

    e2e = random.uniform(1500, 6000)
    tool = random.uniform(300, 1500)
    return RunResult(
        architecture=architecture, model=model_string, scenario=scenario.name,
        concurrency=concurrency, run_idx=run_idx, warmup=warmup,
        intent_variant=run_idx % len(scenario.intents),
        e2e_ms=e2e, selection_ms=random.uniform(200, 900),
        llm_ms=e2e - tool, tool_ms=tool, format_ms=random.uniform(100, 600),
        cpu_avg=random.uniform(5, 30), cpu_peak=random.uniform(30, 90),
        rss_avg_mb=random.uniform(150, 250), rss_peak_mb=random.uniform(250, 400),
        prompt_tokens=random.randint(800, 2500),
        completion_tokens=random.randint(50, 400),
        total_tokens=random.randint(900, 2900),
        selected=expected, expected=expected,
        routing_correct=(rc := random.random() > 0.1),
        intended_skill=scenario.expected_skill, native_call=True,
        decision_correct=rc,
    )


def _quiet_logging() -> None:
    """
    Silence framework log noise during benchmark campaigns.

    Expected per-run failures (e.g. a small model hallucinating a tool name)
    make ADK log multi-page tracebacks that drown the progress output.  The
    error of every failed run is already captured in the RunResult and lands
    in the raw JSON / JSONL logs, so the console only needs the one-line
    progress messages the experiment driver prints.
    """
    for name in ("google", "google_adk", "LiteLLM", "litellm", "httpx"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    # ADK emits an [EXPERIMENTAL] UserWarning per FunctionTool construction.
    warnings.filterwarnings("ignore", category=UserWarning, module="google.adk")
    # litellm prints a "Give Feedback / Get Help" banner on every failed
    # request, bypassing the logging system — turn it off explicitly.
    try:
        import litellm
        litellm.suppress_debug_info = True
    except ImportError:
        pass  # --dry-run works without litellm installed


def main() -> None:
    args = _parse_args()
    _quiet_logging()
    cfg = _apply_overrides(load_config(args.config), args)

    # Select the experiments to run.
    if args.experiment:
        if args.experiment not in cfg.experiments:
            sys.exit(f"Unknown experiment '{args.experiment}'. "
                     f"Available: {', '.join(cfg.experiments)}")
        experiment_names = [args.experiment]
    else:
        experiment_names = list(cfg.experiments)

    run_fn = _dry_run_execute if args.dry_run else None

    for name in experiment_names:
        exp = cfg.experiments[name]
        run_id = new_run_id(name)
        print(f"\n=== Experiment: {name}  (run ID: {run_id}) ===")
        if args.dry_run:
            print("    DRY RUN — synthetic metrics, no LLM calls\n")

        if run_fn is not None:
            results, throughput = asyncio.run(run_experiment(exp, cfg, run_fn=run_fn))
        else:
            results, throughput = asyncio.run(run_experiment(exp, cfg))

        paths = write_outputs(name, run_id, cfg, results, throughput)
        print("\nOutputs written:")
        for kind, path in paths.items():
            print(f"  {kind:15s} {path}")

        # Automatically produce figures and LaTeX tables from the raw data.
        plots.generate(name, run_id, cfg)
        latex_tables.generate(name, run_id, cfg)

    print("\nDone.")


if __name__ == "__main__":
    main()
