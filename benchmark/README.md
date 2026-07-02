# InTrust Architecture Benchmark

A reproducible benchmarking framework comparing two Google ADK architectural
styles for intent-driven trustworthiness assessment, using InTrust as the
implementation platform:

| | Architecture A — Multi-agent | Architecture B — Single agent + skills |
|---|---|---|
| Orchestrator | 1 root `LlmAgent`, no tools | 1 `LlmAgent` with all skills as tools |
| Downstream | 1 specialist `LlmAgent` per assessment (own LLM instance, own prompt, one tool) | — |
| Routing | ADK `transfer_to_agent` delegation | LLM tool selection |
| LLM calls per run | 3 (route → tool call → summary) | 2 (tool call → summary) |

Everything else — intents, prompts, assessment tools, inputs, ADK version,
hardware — is identical.  The orchestration architecture is the **only
independent variable**.

The benchmark code lives entirely in this `benchmark/` package; the
production InTrust service is not modified and keeps working as before.

---

## 1. Installation

From the repository root (Python 3.11+ required; the repo venv already has
the production dependencies):

```bash
# Activate the project venv first, then:
pip install -r benchmark/requirements.txt
```

This installs `google-adk[extensions]` (which brings `litellm`, needed to
talk to Ollama), `psutil` (CPU/memory sampling) and `matplotlib` (figures).

### Install Ollama and pull the models

Install Ollama from <https://ollama.com/download> and make sure the server
is running (`ollama serve`, default URL `http://localhost:11434`).

Pull the models used by the two experiments:

```bash
# Experiment 1 — family comparison
ollama pull qwen3:8b
ollama pull llama3.1:8b
ollama pull gemma3:4b
ollama pull mistral:7b
ollama pull phi4

# Experiment 2 — Qwen scaling study (qwen3:8b already pulled above)
ollama pull qwen3:4b
ollama pull qwen3:14b
```

### One-time scenario preparation

- **Bandit / Trivy filesystem scans** need nothing: they scan the frozen
  sample code committed under `benchmark/data/sample_code/`.
- **Trivy Docker image scan**: pull the pinned image once and pre-download
  the Trivy vulnerability database so neither download pollutes the
  measured timings:

  ```bash
  docker pull python:3.11-slim
  trivy image --download-db-only
  ```

- **Trivy Kubernetes scan** (disabled by default): requires a live cluster
  reachable through your kubeconfig; enable it in the config file.

---

## 2. Configuration

All benchmark parameters live in [`config.default.toml`](config.default.toml).
To change anything, copy the file and pass your copy on the command line —
no code changes are ever needed:

```bash
cp benchmark/config.default.toml my_config.toml
# edit my_config.toml ...
python -m benchmark.run_benchmark --config my_config.toml
```

Key settings:

| Setting | Default | Meaning |
|---|---|---|
| `warmup_runs` | 5 | unrecorded runs before measurement (model loading, caches) |
| `measured_runs` | 30 | recorded runs per (architecture × model × scenario) cell |
| `seed` | 42 | framework-side random seed (run ordering; LLM sampling is server-side) |
| `run_timeout_sec` | 600 | a run exceeding this is recorded as failed |
| `ollama_api_base` | `http://localhost:11434` | Ollama server URL |
| `[experiments.*].models` | see file | model list per experiment (LiteLLM `ollama_chat/<name>` strings) |
| `[experiments.*].concurrency_levels` | 1 / 1,5,10,20 | throughput mode levels |
| `[scenarios]` | k8s off | enable/disable individual assessment scenarios |

---

## 3. Running the experiments

Always run from the **repository root**.

```bash
# Everything (both experiments, full grid):
python -m benchmark.run_benchmark

# One experiment:
python -m benchmark.run_benchmark --experiment family_comparison
python -m benchmark.run_benchmark --experiment scaling_study
```

Each execution gets a unique run ID (e.g.
`family_comparison_20260703-101530_ab12cd34`) and writes:

```
results/
├── family_comparison/
│   ├── raw/       <run_id>.json  (full records incl. event timelines)
│   │              <run_id>.csv   (flat, one row per measured run — plot-ready)
│   │              <run_id>_throughput.csv
│   ├── plots/     latency_boxplot.png, cpu_usage.png, memory_usage.png,
│   │              token_usage.png, throughput.png
│   ├── latex/     latency.tex, cpu.tex, memory.tex, tokens.tex,
│   │              routing.tex, throughput.tex
│   └── summary.md
├── scaling_study/  (same layout)
└── logs/          <run_id>.jsonl  (structured per-run log)
```

Figures and LaTeX tables are generated automatically after each run.

### Quick verification (before a long campaign)

```bash
# Full pipeline WITHOUT Ollama (synthetic metrics — checks all wiring):
python -m benchmark.run_benchmark --dry-run --runs 3 --warmup 1

# One real run against the smallest model:
python -m benchmark.run_benchmark --experiment scaling_study \
    --model ollama_chat/qwen3:4b --scenario bandit_static_code \
    --runs 1 --warmup 0
```

---

## 4. Collected metrics (and why)

| Metric | How | Why it matters for the paper |
|---|---|---|
| End-to-end latency (min/max/mean/median/stdev/p95) | `perf_counter` around the full request → response cycle | the primary user-visible cost of each architecture |
| Skill-selection latency | timestamp of the first routing decision (tool call in B, `transfer_to_agent` in A) | isolates the routing overhead the architecture adds |
| LLM time / tool time / formatting time | ADK event timestamps + a timing wrapper around each assessment tool | separates architecture overhead (LLM calls) from constant tool cost |
| CPU avg/peak, RSS avg/peak | `psutil` sampler at 100 ms | resource cost comparison; multi-agent does more LLM round-trips |
| Prompt/completion/total tokens | `event.usage_metadata` (recorded as `N/A` when unavailable — never fails the run) | token economy differs: 1 shared context vs. several smaller ones |
| Routing accuracy | selected skill/agent vs. expected per scenario | do smaller models route worse in one architecture? |
| Throughput (req/s, failures) | waves of N concurrent runs via `asyncio.gather` | behaviour under load per architecture |

Warm-up runs are excluded from every statistic.  Each run uses a **fresh
agent and a fresh ADK session** — no conversation history is ever reused.

---

## 5. Reproducing published results

1. Same machine class, OS, and software versions (`pip freeze`, Ollama
   version, and the exact model tags matter — model tags like `qwen3:8b`
   are mutable upstream, so record `ollama list` output with your results).
2. `python -m benchmark.run_benchmark` with the committed
   `config.default.toml` (seed 42, 5 warm-ups, 30 measured runs).
3. Compare your `results/<experiment>/summary.md` against the published one.

Because LLM token sampling happens inside the Ollama server, individual runs
are not bit-reproducible; the reported statistics (30 runs per cell) are the
reproducible quantity.

## 6. Regenerating figures and tables

Both readers work from the stored raw CSVs — no benchmark re-run needed:

```bash
python -m benchmark.plots        --experiment family_comparison
python -m benchmark.latex_tables --experiment family_comparison

# A specific (older) execution instead of the latest:
python -m benchmark.plots --experiment scaling_study --run-id <run_id>
```

The `.tex` files are self-contained booktabs tables ready for `\input{}`
(the paper preamble needs `\usepackage{booktabs}`).

## 7. Extending the framework

- **New skill/assessment**: add the skill to the production `skills/`
  directory as usual (plus its `docs/skills/*.md`), then add a scenario
  entry in `benchmark/scenarios.py` and a frozen intent JSON under
  `benchmark/data/intents/`.  Both architectures pick it up automatically.
- **New model**: add its `ollama_chat/<tag>` string to a model list in the
  config — nothing else.
- **New LLM provider**: add a branch in `benchmark/model_factory.py`.
- **New metric**: extend `RunResult` in `benchmark/metrics.py` and fill it
  in `benchmark/runner.py`; add a column to `_CSV_COLUMNS` in
  `benchmark/report_writer.py`.
