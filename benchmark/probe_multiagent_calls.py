"""
Loop probe: run a few real assessment runs and print the per-run LLM-call and
tool-call counts, to confirm whether an architecture converges in the intended
number of model calls (single-agent: 2, multi-agent: 3) or loops.

This exists to diagnose the 27B multi-agent latency/token blow-up: the merged
scaling study shows 27B multi-agent runs consuming ~250k prompt tokens each
(vs ~4k single-agent), consistent with the delegate-and-answer flow
re-invoking the model dozens of times per run instead of three. This probe
reads the exact count from the ADK event stream.

Unlike ``run_benchmark``, this writes NOTHING under ``results/`` — it calls the
single-run executor directly and only prints. So it is safe to run against a
results directory that already holds committed data (no summary/plot overwrite).

Run it where the model is served (e.g. inside a GPU allocation with Ollama up,
or via ``benchmark/slurm/probe_27b_loop.job``). Point it at that Ollama with
the ``INTRUST_OLLAMA_API_BASE`` environment variable if it is not the default.

Examples (from the repository root):

    # The suspect case — 27B multi-agent, five runs on the static-code scenario:
    python -m benchmark.probe_multiagent_calls \\
        --model ollama_chat/qwen3.5:27b --scenario bandit_static_code \\
        --architecture multi_agent --runs 5

    # The clean contrast — same model, single agent:
    python -m benchmark.probe_multiagent_calls \\
        --model ollama_chat/qwen3.5:27b --scenario bandit_static_code \\
        --architecture single_agent --runs 5
"""

import argparse
import asyncio
import statistics
import sys
from pathlib import Path

# Allow ``python -m benchmark.probe_multiagent_calls`` and plain-script use.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from orchestrator.skill_loader import load_skills  # noqa: E402

from benchmark.config import load_config  # noqa: E402
from benchmark.runner import execute_run  # noqa: E402
from benchmark.scenarios import load_scenarios  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Probe per-run LLM/tool call counts (loop diagnostic).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--config", type=Path, default=None,
                   help="path to a TOML config (default: config.default.toml)")
    p.add_argument("--model", default="ollama_chat/qwen3.5:27b",
                   help="litellm model string to probe")
    p.add_argument("--scenario", default="bandit_static_code",
                   help="scenario key (one of the four known scenarios)")
    p.add_argument("--architecture", default="multi_agent",
                   choices=["single_agent", "multi_agent"],
                   help="architecture to probe")
    p.add_argument("--runs", type=int, default=5,
                   help="number of measured runs to execute")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    cfg = load_config(args.config)
    skills = load_skills().list()
    scenarios = load_scenarios([args.scenario])
    if not scenarios:
        sys.exit(f"Unknown scenario '{args.scenario}'.")
    scenario = scenarios[0]

    expected = 3 if args.architecture == "multi_agent" else 2
    print(f"Probe: {args.architecture} / {args.model} / {scenario.name}")
    print(f"Ollama: {cfg.ollama_api_base}")
    print(f"Intended LLM calls per run: {expected} "
          f"(a much larger count means the run looped)\n")
    header = (f"{'run':>3}  {'status':<7}{'e2e(s)':>9}{'llm_calls':>11}"
              f"{'tool_calls':>12}{'prompt_tok':>12}{'total_tok':>11}"
              f"{'routing':>9}")
    print(header)
    print("-" * len(header))

    llm_counts = []
    for i in range(args.runs):
        r = asyncio.run(execute_run(
            architecture=args.architecture,
            model_string=args.model,
            scenario=scenario,
            skills=skills,
            cfg=cfg,
            run_idx=i,
            concurrency=1,
            warmup=False,
        ))
        if r.llm_call_count is not None:
            llm_counts.append(r.llm_call_count)
        print(f"{i:>3}  {r.status:<7}{(r.e2e_ms or 0) / 1000:>9.1f}"
              f"{_fmt(r.llm_call_count):>11}{_fmt(r.tool_call_count):>12}"
              f"{_fmt(r.prompt_tokens):>12}{_fmt(r.total_tokens):>11}"
              f"{str(r.routing_correct):>9}")

    if llm_counts:
        print(f"\nLLM calls per run — mean {statistics.mean(llm_counts):.1f}, "
              f"median {statistics.median(llm_counts):.0f}, "
              f"min {min(llm_counts)}, max {max(llm_counts)} "
              f"(intended {expected}).")
        if statistics.median(llm_counts) > expected + 1:
            print("=> Confirms a non-convergent loop: the run re-invokes the "
                  "model well beyond the intended flow.")
        else:
            print("=> Converges as intended (no loop).")


def _fmt(v) -> str:
    """Render None as 'n/a', otherwise the value."""
    return "n/a" if v is None else str(v)


if __name__ == "__main__":
    main()
