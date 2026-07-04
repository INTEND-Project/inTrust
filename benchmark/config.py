"""
Benchmark configuration loading.

Reads a TOML configuration file (see ``config.default.toml``) into a plain
``BenchmarkConfig`` dataclass with explicit validation.  TOML was chosen
because Python 3.11+ can read it with the standard-library ``tomllib``
module — no extra dependency.

Everything that varies between benchmark executions (models, experiments,
scenarios, run counts, seeds, paths) lives in the config file so that
experiments are reproducible from configuration alone.
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


# Repository root = parent of the benchmark/ directory.
# Used to resolve relative paths so the benchmark works no matter which
# directory it is launched from.
REPO_ROOT = Path(__file__).resolve().parent.parent

# The default configuration shipped with the repository.
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.default.toml"


@dataclass(frozen=True)
class ExperimentConfig:
    """Configuration of one experiment (a grid of models x architectures)."""

    name: str
    models: List[str]
    architectures: List[str]
    concurrency_levels: List[int]


@dataclass(frozen=True)
class BenchmarkConfig:
    """Validated, immutable benchmark configuration."""

    results_dir: Path
    ollama_api_base: str
    seed: int
    warmup_runs: int
    measured_runs: int
    run_timeout_sec: int
    experiments: Dict[str, ExperimentConfig]
    enabled_scenarios: List[str]
    provider_type: str = "ollama"
    # Client-side timeout for a single LLM request (litellm 'timeout' kwarg).
    request_timeout_sec: int = 300
    # Extra kwargs forwarded verbatim to every LiteLlm model instance
    # (e.g. think=false, num_predict, num_ctx for Ollama).
    model_kwargs: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


# Architectures the framework knows how to build (see arch_single.py /
# arch_multi.py).  Used for validation only.
_KNOWN_ARCHITECTURES = {"single_agent", "multi_agent"}

# Scenario keys the framework knows (see scenarios.py).
_KNOWN_SCENARIOS = {
    "bandit_static_code",
    "trivy_filesystem",
    "trivy_docker_image",
    "trivy_kubernetes",
}


def load_config(config_path: Path | None = None) -> BenchmarkConfig:
    """
    Load and validate a benchmark configuration file.

    Parameters
    ----------
    config_path : Path, optional
        Path to a TOML config file.  Defaults to ``config.default.toml``.

    Returns
    -------
    BenchmarkConfig

    Raises
    ------
    ValueError
        With a plain-English message whenever the file is missing a required
        section or contains an unknown architecture/scenario name.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ValueError(f"Config file not found: {path}")

    with open(path, "rb") as fh:
        raw = tomllib.load(fh)

    # --- [general] section -------------------------------------------------
    general = raw.get("general")
    if general is None:
        raise ValueError(f"{path}: missing required [general] section")

    results_dir = Path(general.get("results_dir", "results"))
    if not results_dir.is_absolute():
        results_dir = REPO_ROOT / results_dir

    # --- [experiments.*] sections -------------------------------------------
    experiments: Dict[str, ExperimentConfig] = {}
    for name, exp in raw.get("experiments", {}).items():
        architectures = exp.get("architectures", [])
        unknown = set(architectures) - _KNOWN_ARCHITECTURES
        if unknown:
            raise ValueError(
                f"{path}: experiment '{name}' lists unknown architecture(s) "
                f"{sorted(unknown)}. Known: {sorted(_KNOWN_ARCHITECTURES)}"
            )
        if not exp.get("models"):
            raise ValueError(f"{path}: experiment '{name}' has an empty models list")
        experiments[name] = ExperimentConfig(
            name=name,
            models=list(exp["models"]),
            architectures=list(architectures),
            concurrency_levels=list(exp.get("concurrency_levels", [1])),
        )
    if not experiments:
        raise ValueError(f"{path}: no [experiments.*] sections defined")

    # --- [scenarios] section -------------------------------------------------
    scenario_flags = raw.get("scenarios", {})
    unknown = set(scenario_flags) - _KNOWN_SCENARIOS
    if unknown:
        raise ValueError(
            f"{path}: unknown scenario key(s) {sorted(unknown)}. "
            f"Known: {sorted(_KNOWN_SCENARIOS)}"
        )
    enabled_scenarios = [name for name, on in scenario_flags.items() if on]
    if not enabled_scenarios:
        raise ValueError(f"{path}: all scenarios are disabled — nothing to benchmark")

    provider = raw.get("provider", {})

    # The Ollama URL can be overridden through the environment.  Used by the
    # Slurm jobs (benchmark/slurm/), where the server runs on a per-job port,
    # so no config file editing is needed per submission.
    ollama_api_base = os.environ.get(
        "INTRUST_OLLAMA_API_BASE",
        general.get("ollama_api_base", "http://localhost:11434"),
    )

    return BenchmarkConfig(
        results_dir=results_dir,
        ollama_api_base=ollama_api_base,
        seed=int(general.get("seed", 42)),
        warmup_runs=int(general.get("warmup_runs", 5)),
        measured_runs=int(general.get("measured_runs", 30)),
        run_timeout_sec=int(general.get("run_timeout_sec", 600)),
        experiments=experiments,
        enabled_scenarios=enabled_scenarios,
        provider_type=provider.get("type", "ollama"),
        request_timeout_sec=int(provider.get("request_timeout_sec", 300)),
        model_kwargs=dict(provider.get("model_kwargs", {})),
        extra=raw,
    )
