"""
Experiment driver: iterates the full (model x architecture x scenario x
concurrency) grid, handling warm-up runs, measured runs, resource sampling
and the concurrent-throughput mode.

Methodology
-----------
- Warm-up runs execute the complete pipeline but are flagged ``warmup=True``
  and excluded from every statistic.  They exist so that model loading,
  OS caches and tool databases (e.g. the Trivy vulnerability DB) do not
  pollute the measurements.
- Measured runs at concurrency 1 are strictly sequential, each with its own
  CPU/memory sampler.
- Throughput mode (concurrency N > 1) launches waves of N runs with
  ``asyncio.gather`` and records requests-per-second per concurrency level.
  The resource sampler then measures the whole process across the wave.
- The random seed is set once per experiment.  It governs framework-side
  behaviour only; LLM token sampling happens inside the Ollama server and
  cannot be seeded from here (documented limitation).
"""

import asyncio
import random
import time
from typing import Any, Dict, List, Tuple

from orchestrator.skill_loader import load_skills

from .config import BenchmarkConfig, ExperimentConfig
from .instrumentation import ResourceSampler
from .metrics import RunResult
from .model_factory import unload_model
from .runner import execute_run
from .scenarios import Scenario, load_scenarios


async def run_experiment(
    exp: ExperimentConfig,
    cfg: BenchmarkConfig,
    run_fn=execute_run,
) -> Tuple[List[RunResult], List[Dict[str, Any]]]:
    """
    Execute one complete experiment grid.

    Parameters
    ----------
    run_fn : coroutine function, optional
        The function that executes a single run.  Defaults to the real
        ``runner.execute_run``; the ``--dry-run`` CLI mode injects a stub
        here so the whole reporting pipeline can be tested without Ollama.

    Returns
    -------
    (results, throughput_records)
        ``results`` — one RunResult per executed run (warm-ups included,
        flagged).  ``throughput_records`` — one summary dict per
        (architecture, model, scenario, concurrency) cell with
        requests-per-second and failure counts.
    """
    random.seed(cfg.seed)

    # Production skills are loaded ONCE; per-run instrumentation copies are
    # created inside the architecture builders.
    skills = load_skills().list()
    scenarios = load_scenarios(cfg.enabled_scenarios)

    results: List[RunResult] = []
    throughput_records: List[Dict[str, Any]] = []

    total_cells = len(exp.models) * len(exp.architectures) * len(scenarios)
    cell_no = 0

    prev_model = None
    for model in exp.models:
        # Evict the previous model so only the current one is resident on the
        # GPU (clean per-model VRAM/RSS); the reload lands in the warm-ups.
        # Skipped under --dry-run (no real Ollama server to talk to).
        if (prev_model is not None and prev_model != model
                and run_fn is execute_run):
            unload_model(prev_model, cfg)
        prev_model = model
        for architecture in exp.architectures:
            for scenario in scenarios:
                cell_no += 1
                print(
                    f"[{cell_no}/{total_cells}] {exp.name}: "
                    f"{architecture} / {model} / {scenario.name}"
                )

                # ---- warm-up runs (never recorded in statistics) ----------
                for i in range(cfg.warmup_runs):
                    run = await _sampled_run(
                        architecture, model, scenario, skills, cfg,
                        run_idx=i, warmup=True, run_fn=run_fn,
                    )
                    results.append(run)
                    print(f"    warmup {i + 1}/{cfg.warmup_runs}: "
                          f"{run.status} {run.e2e_ms:.0f} ms")

                # ---- measured runs, per concurrency level ------------------
                for concurrency in exp.concurrency_levels:
                    if concurrency <= 1:
                        cell_runs = await _run_sequential(
                            architecture, model, scenario, skills, cfg, run_fn
                        )
                        wall_sec = sum(r.e2e_ms for r in cell_runs) / 1000.0
                    else:
                        cell_runs, wall_sec = await _run_concurrent(
                            architecture, model, scenario, skills, cfg,
                            concurrency, run_fn,
                        )
                    results.extend(cell_runs)

                    ok = [r for r in cell_runs if r.status == "OK"]
                    throughput_records.append({
                        "architecture": architecture,
                        "model": model,
                        "scenario": scenario.name,
                        "concurrency": concurrency,
                        "total_runs": len(cell_runs),
                        "failures": len(cell_runs) - len(ok),
                        "wall_sec": wall_sec,
                        "rps": len(ok) / wall_sec if wall_sec > 0 else 0.0,
                        "avg_latency_ms": (
                            sum(r.e2e_ms for r in ok) / len(ok) if ok else 0.0
                        ),
                    })
                    print(f"    concurrency {concurrency}: "
                          f"{len(ok)}/{len(cell_runs)} ok, "
                          f"{throughput_records[-1]['rps']:.3f} req/s")

    return results, throughput_records


async def _sampled_run(
    architecture: str,
    model: str,
    scenario: Scenario,
    skills,
    cfg: BenchmarkConfig,
    run_idx: int,
    warmup: bool,
    concurrency: int = 1,
    run_fn=execute_run,
) -> RunResult:
    """One run wrapped with its own CPU/memory sampler."""
    sampler = ResourceSampler()
    sampler.start()
    run = await run_fn(
        architecture, model, scenario, skills, cfg,
        run_idx=run_idx, concurrency=concurrency, warmup=warmup,
    )
    stats = sampler.stop()
    # Keys match RunResult field names (harness, server, and GPU metrics).
    for key, value in stats.items():
        setattr(run, key, value)
    return run


async def _run_sequential(
    architecture: str, model: str, scenario: Scenario, skills,
    cfg: BenchmarkConfig, run_fn=execute_run,
) -> List[RunResult]:
    """The standard measurement mode: measured runs one after another."""
    runs: List[RunResult] = []
    for i in range(cfg.measured_runs):
        run = await _sampled_run(
            architecture, model, scenario, skills, cfg,
            run_idx=i, warmup=False, run_fn=run_fn,
        )
        runs.append(run)
        print(f"    run {i + 1}/{cfg.measured_runs}: "
              f"{run.status} {run.e2e_ms:.0f} ms "
              f"routing={'ok' if run.routing_correct else 'MISS'}")
    return runs


async def _run_concurrent(
    architecture: str, model: str, scenario: Scenario, skills,
    cfg: BenchmarkConfig, concurrency: int, run_fn=execute_run,
) -> Tuple[List[RunResult], float]:
    """
    Throughput mode: launch the measured runs in waves of ``concurrency``
    parallel requests and measure the total wall time.

    The resource sampler covers the whole wave (the per-process CPU/memory
    of N concurrent runs cannot be attributed to individual runs).
    """
    runs: List[RunResult] = []
    sampler = ResourceSampler()
    sampler.start()
    wave_start = time.perf_counter()

    run_idx = 0
    while run_idx < cfg.measured_runs:
        wave_size = min(concurrency, cfg.measured_runs - run_idx)
        wave = await asyncio.gather(*[
            run_fn(
                architecture, model, scenario, skills, cfg,
                run_idx=run_idx + k, concurrency=concurrency, warmup=False,
            )
            for k in range(wave_size)
        ])
        runs.extend(wave)
        run_idx += wave_size

    wall_sec = time.perf_counter() - wave_start
    stats = sampler.stop()
    # Whole-process resource stats are assigned to every run in the wave set.
    for run in runs:
        run.cpu_avg = stats["cpu_avg"]
        run.cpu_peak = stats["cpu_peak"]
        run.rss_avg_mb = stats["rss_avg_mb"]
        run.rss_peak_mb = stats["rss_peak_mb"]
    return runs, wall_sec
